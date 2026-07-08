"""
Perseus Vault x CockroachDB - live interactive demo.

Demonstrates the CockroachDB x AWS entry's thesis in the browser: CockroachDB is a
single, transactional, distributed source of truth that stores an agent's structured
facts AND their vector embeddings in ONE system, queried with native vector search
(ORDER BY embedding <-> query_vector). No separate vector database; no consistency gap.

This is REAL CockroachDB (a single-node cockroach container, the same engine as
CockroachDB Cloud) with the entry's real schema: a VECTOR column + vector index +
the <-> distance operator. Nothing here is simulated.

Honest scope for a public, keyless demo:
  * The database is genuinely CockroachDB, self-hosted single-node (vs Cloud in the
    submitted entry). Same SQL, same VECTOR type, same operators.
  * Embeddings are produced by a LOCAL model (model2vec, baked into the image) so the
    demo needs no API key and costs nothing per query. The submitted entry uses Amazon
    Bedrock Titan v2 embeddings; here the embedder is swapped for a local one. The
    embeddings are unit-normalized so the <-> (L2) ordering equals cosine ranking.
  * Each visitor is sandboxed by a cookie-scoped agent_id; writes are rate-limited,
    capped, and reaped after idle so the shared cluster stays clean.
"""

from __future__ import annotations

import math
import os
import threading
import time
import uuid

import psycopg2
from flask import Flask, jsonify, make_response, request
from model2vec import StaticModel

app = Flask(__name__)

DSN = os.environ.get("CRDB_DSN",
                     "postgresql://root@cockroach:26257/defaultdb?sslmode=disable")
MODEL_NAME = os.environ.get("M2V_MODEL", "minishlab/potion-base-8M")

# --- local embedder (baked into the image; loads offline) -------------------
_MODEL = StaticModel.from_pretrained(MODEL_NAME)
DIM = len(_MODEL.encode(["dimension probe"])[0])


def embed(text: str) -> list[float]:
    v = _MODEL.encode([text])[0]
    n = math.sqrt(sum(float(x) * float(x) for x in v)) or 1.0
    return [float(x) / n for x in v]           # unit-normalized -> <-> == cosine


def vec_lit(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


# --- CockroachDB ------------------------------------------------------------
DDL = f"""
CREATE TABLE IF NOT EXISTS vault_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id STRING NOT NULL,
    content STRING NOT NULL,
    embedding VECTOR({DIM}),
    created_at TIMESTAMPTZ DEFAULT now(),
    INDEX (agent_id, created_at)
)
""".strip()

_INIT_DONE = False
_INIT_LOCK = threading.Lock()
CRDB_VERSION = "connecting..."
VECTOR_INDEX = False


def _conn():
    return psycopg2.connect(DSN, connect_timeout=5)


def _init_once() -> None:
    global _INIT_DONE, CRDB_VERSION, VECTOR_INDEX
    with _INIT_LOCK:
        if _INIT_DONE:
            return
        last = None
        for _ in range(60):                    # wait for cockroach to accept conns
            try:
                c = _conn()
                break
            except Exception as e:             # noqa: BLE001
                last = e
                time.sleep(2)
        else:
            raise RuntimeError(f"CockroachDB not reachable: {last}")
        c.autocommit = True
        with c.cursor() as cur:
            cur.execute("SELECT version()")
            CRDB_VERSION = cur.fetchone()[0].split(" (")[0]
            try:                               # vector index is a cluster feature
                cur.execute("SET CLUSTER SETTING feature.vector_index.enabled = true")
            except Exception:                  # noqa: BLE001
                pass
            cur.execute(DDL)
            try:                               # add the ANN index if the build supports it
                cur.execute("CREATE VECTOR INDEX IF NOT EXISTS embed_idx "
                            "ON vault_entries (embedding vector_cosine_ops)")
                VECTOR_INDEX = True
            except Exception:                  # noqa: BLE001 - exact <-> search still works
                VECTOR_INDEX = False
        c.close()
        _INIT_DONE = True


# --- per-visitor sandbox ----------------------------------------------------
IDLE_TTL = "30 minutes"
MAX_ROWS_PER_SID = 200
MAX_TEXT = 500
MAX_QUERY = 200
RATE_MAX = 60
RATE_WINDOW = 60.0
_RATE: dict[str, list[float]] = {}
_RATE_LOCK = threading.Lock()


def _sid(req) -> str:
    return req.cookies.get("cr_sid") or uuid.uuid4().hex


def _rate_ok(sid: str) -> bool:
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE.get(sid, []) if now - t < RATE_WINDOW]
        if len(hits) >= RATE_MAX:
            _RATE[sid] = hits
            return False
        hits.append(now)
        _RATE[sid] = hits
        return True


def _resp(sid: str, payload: dict, status: int = 200):
    r = make_response(jsonify(payload), status)
    r.set_cookie("cr_sid", sid, max_age=1800, samesite="Lax", secure=True, httponly=True)
    return r


def _reap(cur) -> None:
    cur.execute(f"DELETE FROM vault_entries WHERE created_at < now() - INTERVAL '{IDLE_TTL}'")


# --- API --------------------------------------------------------------------
@app.route("/api/remember", methods=["POST"])
def api_remember():
    _init_once()
    sid = _sid(request)
    if not _rate_ok(sid):
        return _resp(sid, {"error": "rate limited - slow down"}, 429)
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()[:MAX_TEXT]
    if not content:
        return _resp(sid, {"error": "empty text"}, 400)
    c = _conn()
    c.autocommit = True
    try:
        with c.cursor() as cur:
            _reap(cur)
            cur.execute("SELECT count(*) FROM vault_entries WHERE agent_id = %s", (sid,))
            if cur.fetchone()[0] >= MAX_ROWS_PER_SID:
                return _resp(sid, {"error": "demo store full - hit Reset"}, 409)
            cur.execute(
                "INSERT INTO vault_entries (agent_id, content, embedding) "
                "VALUES (%s, %s, %s::VECTOR)",
                (sid, content, vec_lit(embed(content))),
            )
            cur.execute("SELECT count(*) FROM vault_entries WHERE agent_id = %s", (sid,))
            active = cur.fetchone()[0]
    finally:
        c.close()
    return _resp(sid, {"ok": True, "active": active})


@app.route("/api/recall", methods=["POST"])
def api_recall():
    _init_once()
    sid = _sid(request)
    if not _rate_ok(sid):
        return _resp(sid, {"error": "rate limited - slow down"}, 429)
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()[:MAX_QUERY]
    if not query:
        return _resp(sid, {"error": "empty query"}, 400)
    qv = vec_lit(embed(query))
    c = _conn()
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT content, created_at, embedding <-> %s::VECTOR AS distance "
                "FROM vault_entries WHERE agent_id = %s ORDER BY distance LIMIT 5",
                (qv, sid),
            )
            hits = [{"content": r[0], "distance": round(float(r[2]), 4)}
                    for r in cur.fetchall()]
            cur.execute("SELECT count(*) FROM vault_entries WHERE agent_id = %s", (sid,))
            active = cur.fetchone()[0]
    finally:
        c.close()
    sql = ("SELECT content, embedding <-> $query AS distance\n"
           "FROM vault_entries WHERE agent_id = $you\n"
           "ORDER BY distance LIMIT 5;")
    return _resp(sid, {"ok": True, "hits": hits, "active": active, "sql": sql})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    _init_once()
    sid = _sid(request)
    c = _conn()
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute("DELETE FROM vault_entries WHERE agent_id = %s", (sid,))
    finally:
        c.close()
    return _resp(sid, {"ok": True, "active": 0})


@app.route("/api/info")
def api_info():
    _init_once()
    return jsonify({"crdb_version": CRDB_VERSION, "vector_index": VECTOR_INDEX,
                    "dim": DIM, "embedder": MODEL_NAME, "ddl": DDL})


@app.route("/healthz")
def healthz():
    try:
        _init_once()
        c = _conn(); c.close()
        return jsonify({"ok": True, "crdb": CRDB_VERSION})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 503


@app.route("/")
def index():
    return INDEX_HTML


INDEX_HTML = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Perseus Vault x CockroachDB - live demo</title><style>
:root{--bg:#0a0e17;--panel:#121826;--edge:#243044;--ink:#e7eef7;--mut:#8fa3bd;
--crl:#6933ff;--crl2:#8f66ff;--grn:#3ddc97;--gold:#ffc94d;--red:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--crl2)}.wrap{max-width:1060px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:23px;margin:0 0 2px}h1 b{color:var(--crl2)}h1 i{color:var(--mut);font-style:normal}
.sub{color:var(--mut);margin:0 0 14px}
.badge{display:inline-block;font-size:12px;border:1px solid var(--edge);border-radius:20px;
padding:3px 10px;margin:0 6px 6px 0;color:var(--mut)}.badge b{color:var(--grn)}
.banner{border:1px solid var(--gold);border-radius:8px;padding:10px 14px;margin:12px 0;
color:var(--gold);background:rgba(255,201,77,.06);font-size:13px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:10px;padding:16px}
.card h2{font-size:15px;margin:0 0 4px}.step{color:var(--crl2);font-weight:700}
.hint{color:var(--mut);font-size:12.5px;margin:0 0 10px}
input,button{font:inherit}input[type=text]{width:100%;background:#070b12;color:var(--ink);
border:1px solid var(--edge);border-radius:7px;padding:9px 11px}
.row{display:flex;gap:8px;margin-top:8px}.row input{flex:1}
button{background:#182234;color:var(--ink);border:1px solid var(--edge);border-radius:7px;
padding:9px 13px;cursor:pointer}button:hover{border-color:var(--crl2)}
button.go{background:var(--crl);color:#fff;border-color:var(--crl);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 4px}
.chip{font-size:12px;padding:5px 9px;border:1px dashed var(--edge);border-radius:20px;
color:var(--mut);cursor:pointer}.chip:hover{color:var(--ink);border-color:var(--crl2)}
.log{background:#070b12;border:1px solid var(--edge);border-radius:7px;padding:10px;
margin-top:10px;min-height:34px;font-size:13px;white-space:pre-wrap}
.hit{border-left:3px solid var(--grn);padding:6px 10px;margin:7px 0;background:#070b12;border-radius:4px}
.hit .m{color:var(--mut);font-size:12px}.ok{color:var(--grn)}.warn{color:var(--red)}
pre{background:#070b12;border:1px solid var(--edge);border-radius:7px;padding:10px;
overflow:auto;font-size:12.5px;color:var(--crl2)}
.foot{color:var(--mut);font-size:12px;margin-top:22px;border-top:1px solid var(--edge);padding-top:12px}
.stat{color:var(--mut);font-size:12px;margin-top:8px}
</style></head><body><div class=wrap>
<h1><b>Perseus Vault</b> <i>x</i> CockroachDB</h1>
<p class=sub>One distributed, transactional source of truth for an agent's memory -
 structured facts <b>and</b> vector embeddings in the <b>same</b> database, queried
 with native vector search. No separate vector DB, no consistency gap.</p>
<div id=badges>
 <span class=badge>engine: <b id=ver>...</b></span>
 <span class=badge>vector dim: <b id=dim>...</b></span>
 <span class=badge>vector index: <b id=vidx>...</b></span>
 <span class=badge>embedder: <b id=emb>local</b></span>
</div>
<div class=banner>&#9888; Honesty: this is <b>real CockroachDB</b> (single-node, same engine
 as CockroachDB Cloud) with a real <b>VECTOR</b> column and <b>&lt;-&gt;</b> search. Embeddings
 come from a <b>local</b> model (the submitted entry uses Amazon Bedrock Titan v2); vectors are
 unit-normalized so &lt;-&gt; ranks by cosine similarity.</div>
<div class=grid>
 <div class=card>
  <h2><span class=step>1</span> · store a memory (transactional INSERT)</h2>
  <p class=hint>Each fact is embedded and written to CockroachDB in one atomic statement.</p>
  <div class=chips id=chips></div>
  <div class=row><input id=mem type=text maxlength=500
    placeholder="e.g. The primary contact for project Cerberus is Dr. Aris Thorne.">
   <button class=go onclick=remember()>Store</button></div>
  <div class=stat id=stat>rows for your session: 0</div>
  <div class=log id=log1>nothing stored yet.</div>
 </div>
 <div class=card>
  <h2><span class=step>2</span> · recall by meaning (vector search)</h2>
  <p class=hint>Your query is embedded and ranked by <b>embedding &lt;-&gt; query</b> inside CockroachDB.</p>
  <div class=row><input id=q type=text maxlength=200 placeholder="e.g. who is the contact for Cerberus?">
   <button class=go onclick=recall()>Recall</button></div>
  <div class=log id=log2>store a few facts, then ask in your own words.</div>
  <pre id=sql style="display:none"></pre>
  <div style="margin-top:8px"><button onclick=reset()>Reset my data</button></div>
 </div>
</div>
<div class=card style="margin-top:16px">
 <h2>The one table (live DDL)</h2>
 <p class=hint>Structured columns + a native VECTOR column, in one distributed table:</p>
 <pre id=ddl>loading...</pre>
</div>
<p class=foot>CockroachDB x AWS entry ·
 repo <a href="https://github.com/tcconnally/perseus-vault-hackathon">perseus-vault-hackathon</a> ·
 built on <a href="https://github.com/Perseus-Computing-LLC/perseus-vault">Perseus Vault</a> ·
 per-visitor sandbox, auto-reaped when idle. MIT.</p>
</div><script>
const EX=["The primary contact for project Cerberus is Dr. Aris Thorne.",
 "Our production database is CockroachDB, deployed multi-region.",
 "The deploy target for project Phoenix is AWS us-east-1.",
 "Embeddings and structured facts live in the same table.",
 "The on-call lead this week is Dana."];
const chips=document.getElementById('chips');
EX.forEach(t=>{const c=document.createElement('span');c.className='chip';c.textContent=t;
 c.onclick=()=>{document.getElementById('mem').value=t;remember();};chips.appendChild(c);});
async function post(u,b){return (await fetch(u,{method:'POST',
 headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})})).json();}
function setStat(n){document.getElementById('stat').textContent='rows for your session: '+n;}
async function remember(){const el=document.getElementById('mem'),t=el.value.trim();if(!t)return;
 const d=await post('/api/remember',{content:t}),l=document.getElementById('log1');
 if(d.error){l.innerHTML='<span class=warn>'+d.error+'</span>';return;}
 setStat(d.active);el.value='';l.innerHTML='<span class=ok>INSERT ok</span>  "'+esc(t)+'"';}
async function recall(){const q=document.getElementById('q').value.trim();if(!q)return;
 const d=await post('/api/recall',{query:q}),l=document.getElementById('log2');
 if(d.error){l.innerHTML='<span class=warn>'+d.error+'</span>';return;}
 if(!d.hits.length){l.innerHTML='no rows yet - store some facts first.';return;}
 l.innerHTML='<span class=ok>top matches from CockroachDB ('+d.active+' rows):</span>'+
  d.hits.map(h=>'<div class=hit>'+esc(h.content)+'<div class=m>cosine distance '+
  h.distance+'</div></div>').join('');
 const s=document.getElementById('sql');s.style.display='block';s.textContent=d.sql;}
async function reset(){await post('/api/reset',{});setStat(0);
 document.getElementById('log1').textContent='nothing stored yet.';
 document.getElementById('log2').textContent='store a few facts, then ask in your own words.';
 document.getElementById('sql').style.display='none';}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
fetch('/api/info').then(r=>r.json()).then(i=>{document.getElementById('ver').textContent=i.crdb_version;
 document.getElementById('dim').textContent=i.dim;
 document.getElementById('vidx').textContent=i.vector_index?'enabled':'exact <-> (no ANN idx)';
 document.getElementById('emb').textContent=i.embedder;
 document.getElementById('ddl').textContent=i.ddl;});
</script></body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
