# Devpost Submission — Perseus Vault

Copy/paste-ready fields for the **CockroachDB × AWS "Build with Agentic Memory"
Hackathon** (prize: $8,750; deadline: **Aug 18, 2026**).

---

## Project name
**Perseus Vault — Agentic Memory on CockroachDB**

## Elevator pitch (< 200 chars)
> Production-grade memory for AI agents: store, recall-rank, reinforce, and decay — on CockroachDB's distributed vector SQL, embedded with Amazon Bedrock, served from AWS Lambda.

*(176 characters.)*

---

## What it does
Perseus Vault is an agentic **memory core**. It gives an AI agent the three things a
context window can't: durable recall across sessions, ranking that reflects what
actually matters, and the ability to forget noise.

- **Store** — the agent writes a memory (text + flexible JSONB metadata); Amazon
  Bedrock (Titan Embeddings V2) turns it into a vector, and it's committed to
  CockroachDB in one transaction alongside an append-only event record.
- **Recall (ranked)** — a query pulls a candidate pool via CockroachDB's distributed
  vector index, then re-ranks with a composite score:
  `salience × (0.60·similarity + 0.25·recency + 0.15·frequency)`. The memory the
  agent leans on beats the one that's merely closest.
- **Reinforce** — recalled memories gain salience and an access-count bump, so useful
  knowledge strengthens with use.
- **Decay** — a scheduled pass ages salience by time-since-use and archives memories
  that fall below threshold, keeping the working set signal-dense. Nothing is
  silently deleted; the `memory_events` log preserves the full history.
- **Inspect** — the CockroachDB MCP Server exposes the same cluster to any MCP client
  for natural-language querying, vector search, and monitoring.

## How we built it
- **Memory engine** — `vault_core.py`: provider-agnostic store/recall/reinforce/decay
  logic. Provider subclasses supply embeddings (`bedrock_agent.py` for Amazon Bedrock,
  `agent.py` for OpenAI as fallback).
- **Data model** — relational and event-sourced (`db_schema.py`): `agents`,
  `memories` (VECTOR + C-SPANN cosine index, JSONB + inverted index, decay/salience
  columns), and `memory_events` (append-only, FK-linked, timestamped). Multi-region
  survivability SQL included.
- **Serving** — `lambda_handler.py` (AWS Lambda via container image) and `handler.py`
  (Flask for local dev), exposing `/remember`, `/recall`, `/decay`, `/health`.
- **MCP integration** — `mcp_config.json` wires the official CockroachDB MCP Server
  (`amineelkouhen/mcp-cockroachdb`, launched via `uvx`) to the same cluster;
  `verify_mcp.py` is a preflight that checks the toolchain, config, and env.
- **Maintenance** — `decay.py` runs a decay pass standalone (schedulable via Amazon
  EventBridge → Lambda).

## Why CockroachDB + AWS
- **One consistent source of truth.** Structured agent state *and* its vector memory
  live in the same distributed, transactional database — no drift between a relational
  store and a bolt-on vector DB, no dual-write inconsistency.
- **Distributed vector indexing.** CockroachDB's native `VECTOR` type + C-SPANN ANN
  index scales similarity search horizontally instead of hitting a single-node ceiling.
- **Survivability.** Multi-region locality (`REGIONAL BY ROW`, `SURVIVE REGION
  FAILURE`) means the agent's memory tolerates zone/region loss.
- **AWS-native.** Amazon Bedrock supplies embeddings with no third-party key; AWS
  Lambda makes "memory survives across stateless invocations" a real, provable demo
  rather than a claim; EventBridge schedules the decay pass.
- **Agent-operable.** The CockroachDB MCP Server lets operators and other agents query
  and monitor the memory store in natural language.

## Category narrative — Agentic Memory Design (primary criterion)
Most "agent memory" is a vector-store lookup: embed, nearest-neighbor, done. That
ignores how memory actually works — it *ranks*, *reinforces*, and *forgets*. Perseus
Vault implements all three as first-class, database-backed behaviors:

1. **Recall ranking** blends semantic similarity with recency and access frequency,
   scaled by a per-memory salience weight — so relevance is contextual, not just
   cosine distance.
2. **Cross-session persistence** is guaranteed by design: the agent runs stateless on
   Lambda and every memory is agent-scoped in CockroachDB, so recall works identically
   after a cold start.
3. **Decay** actively prunes the working set by aging salience and archiving neglected
   memories, while reinforcement strengthens what's used — the memory curates itself.

Every operation is written to an append-only, timestamped `memory_events` table, so
the memory's *behavior over time* is itself auditable and queryable. This is memory
*design*, not memory *storage*.

## Challenges
- Making "cross-session persistence" demonstrable rather than asserted — solved by
  running fully stateless on Lambda so nothing but CockroachDB carries state.
- Ranking beyond nearest-neighbor without a second system — solved with an in-query
  candidate pool plus a composite re-rank driven by columns CockroachDB already tracks.
- Keeping decay non-destructive and auditable — solved with an archive flag
  (`decayed_at`) plus the event log instead of hard deletes.

## What's next
- Semantic clustering / consolidation of related memories.
- Adaptive, per-agent ranking weights learned from recall outcomes.
- Streaming decay via CockroachDB changefeeds (CDC) instead of scheduled batch.

---

## Built with
`CockroachDB` · `CockroachDB MCP Server` · `distributed vector index (C-SPANN)` ·
`AWS Lambda` · `Amazon Bedrock (Titan Embeddings V2)` · `Amazon EventBridge` ·
`Python` · `psycopg2` · `Flask` · `Docker` · `uv/uvx`

## Links
- **Repository:** https://github.com/tcconnally/perseus-vault-hackathon
- **Demo video:** `<ADD UNLISTED YOUTUBE/VIMEO URL AFTER RE-RECORD — see note below>`
- **License:** MIT

---

## ⚠️ Demo video status — RE-RECORD NEEDED before submitting
The committed `demo_video.mp4` was produced against the **previous** build and is now
**out of date**. It shows:
- the old flat `vault_entries` table (now the relational `agents` / `memories` /
  `memory_events` schema), and
- the `ccloud` CLI `CLUSTER_STATE_CREATED` health-check step (removed from the write
  path).

It also **predates the headline features** that anchor the primary judging criterion:
composite recall ranking, salience reinforcement, time-based decay, and the
CockroachDB MCP Server integration.

The narrative arc (agents forget → CockroachDB-backed memory → Bedrock embeddings →
survives a Lambda cold start) is still accurate, so a re-record — not a rewrite — is
what's required.

**To re-record:** the scene script in `generate_video.py` has already been updated to
match the current build (relational schema, ranked recall, decay, MCP). Regenerate on
a machine with `ffmpeg` + `Pillow`:
```bash
pip install pillow
python generate_video.py            # writes demo_video.mp4 in the repo root
```
Then upload the new video (unlisted is fine) and paste its URL into the Devpost
**Demo video** field above.
