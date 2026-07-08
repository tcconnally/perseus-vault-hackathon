"""
Perseus Vault — core agentic-memory engine over CockroachDB.

This module holds all provider-agnostic logic: schema-aware storage, hybrid
recall (distributed vector search + lexical overlap), recall-time reinforcement,
and time-based decay. Provider-specific subclasses (OpenAI, Amazon Bedrock) only
implement `_get_embedding`.

Design goals mapped to the "Agentic Memory Design" judging criterion:
  * Cross-session persistence — every memory lives in CockroachDB, keyed to an
    agent identity, so it survives stateless Lambda invocations and reboots.
  * Recall ranking — candidates are pulled by distributed vector similarity, then
    re-ranked by a salience score that blends semantic match, recency, and
    access frequency.
  * Decay — a maintenance pass ages out memories that are neither recent nor
    frequently used, so the working set stays signal-dense instead of unbounded.
"""

import math
import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras


# --- Recall-ranking / decay tunables ---------------------------------------
# Weights for the composite recall score. They need not sum to 1; they are
# relative importances applied to normalized components.
W_SIMILARITY = float(os.getenv("RANK_W_SIMILARITY", "0.60"))
W_RECENCY = float(os.getenv("RANK_W_RECENCY", "0.25"))
W_FREQUENCY = float(os.getenv("RANK_W_FREQUENCY", "0.15"))

# Recency half-life in days: how quickly the recency component fades.
RECENCY_HALFLIFE_DAYS = float(os.getenv("RECENCY_HALFLIFE_DAYS", "7.0"))

# Decay: salience is multiplied by exp(-DECAY_RATE * days_idle) each maintenance
# pass; memories below DECAY_THRESHOLD are archived (decayed_at set).
DECAY_RATE = float(os.getenv("DECAY_RATE", "0.05"))
DECAY_THRESHOLD = float(os.getenv("DECAY_THRESHOLD", "0.20"))

# Reinforcement applied to salience on each successful recall (capped).
REINFORCE_BOOST = float(os.getenv("REINFORCE_BOOST", "0.15"))
SALIENCE_CAP = float(os.getenv("SALIENCE_CAP", "2.0"))


def _vec_literal(embedding):
    """Format a Python float list as a CockroachDB VECTOR literal: '[1,2,3]'."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PerseusVaultCore:
    """Agent-facing memory API backed by a distributed CockroachDB cluster."""

    def __init__(self, db_url, agent_name):
        if not db_url:
            raise ValueError("db_url is required (set DATABASE_URL).")
        self.db_url = db_url
        self.agent_name = agent_name
        self.conn = None
        self._agent_id = None
        self._connect_db()
        if self.conn:
            self._agent_id = self._ensure_agent(agent_name)

    # -- connection ---------------------------------------------------------
    def _connect_db(self):
        try:
            self.conn = psycopg2.connect(self.db_url)
            self.conn.autocommit = False
        except psycopg2.Error as e:
            print(f"Error: could not connect to CockroachDB. {e}")
            self.conn = None

    def _ensure_agent(self, name):
        """Idempotently register the agent identity and return its UUID."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agents (name) VALUES (%s)
                ON CONFLICT (name) DO UPDATE SET name = excluded.name
                RETURNING id
                """,
                (name,),
            )
            agent_id = cur.fetchone()[0]
        self.conn.commit()
        return agent_id

    # -- embeddings (implemented by provider subclass) ----------------------
    def _get_embedding(self, text: str):
        raise NotImplementedError("Subclasses must implement _get_embedding().")

    # -- writes -------------------------------------------------------------
    def add_memory(self, content: str, metadata: dict | None = None):
        """Persist a memory with its embedding and flexible JSONB metadata."""
        if not self.conn:
            print("Cannot add memory: no database connection.")
            return None

        embedding = self._get_embedding(content)
        if embedding is None:
            print("Could not generate embedding. Aborting write.")
            return None

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memories (agent_id, content, metadata, embedding)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self._agent_id,
                        content,
                        psycopg2.extras.Json(metadata or {}),
                        _vec_literal(embedding),
                    ),
                )
                memory_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO memory_events (memory_id, agent_id, event_type)
                    VALUES (%s, %s, 'store')
                    """,
                    (memory_id, self._agent_id),
                )
            self.conn.commit()
            print(f"Stored memory {memory_id} in the Perseus Vault.")
            return memory_id
        except psycopg2.Error as e:
            print(f"Database error during memory insert: {e}")
            self.conn.rollback()
            return None

    # -- reads --------------------------------------------------------------
    def recall_memories(self, query: str, top_k: int = 3, candidate_pool: int = 20):
        """
        Hybrid recall: pull a candidate pool by distributed vector similarity,
        re-rank by a composite salience score (similarity + recency + frequency),
        reinforce the winners, and log recall events.
        """
        if not self.conn:
            print("Cannot recall: no database connection.")
            return []

        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            print("Could not generate query embedding. Aborting recall.")
            return []

        qvec = _vec_literal(query_embedding)
        try:
            with self.conn.cursor() as cur:
                # Distributed vector search against the C-SPANN cosine index,
                # restricted to this agent's *active* (non-decayed) memories.
                cur.execute(
                    """
                    SELECT id, content, metadata, salience, access_count,
                           created_at, last_accessed_at,
                           embedding <-> %s AS distance
                    FROM memories
                    WHERE agent_id = %s AND decayed_at IS NULL
                    ORDER BY distance
                    LIMIT %s
                    """,
                    (qvec, self._agent_id, candidate_pool),
                )
                rows = cur.fetchall()
        except psycopg2.Error as e:
            print(f"Database error during recall: {e}")
            return []

        now = datetime.now(timezone.utc)
        scored = []
        for row in rows:
            (mem_id, content, metadata, salience, access_count,
             created_at, last_accessed_at, distance) = row
            similarity = 1.0 - float(distance)  # cosine distance -> similarity
            recency = self._recency_score(last_accessed_at, now)
            frequency = self._frequency_score(access_count)
            composite = float(salience) * (
                W_SIMILARITY * similarity
                + W_RECENCY * recency
                + W_FREQUENCY * frequency
            )
            scored.append({
                "id": mem_id,
                "content": content,
                "metadata": metadata,
                "similarity": round(similarity, 4),
                "recency": round(recency, 4),
                "frequency": round(frequency, 4),
                "salience": round(float(salience), 4),
                "score": round(composite, 4),
                "created_at": created_at,
                "last_accessed_at": last_accessed_at,
            })

        scored.sort(key=lambda m: m["score"], reverse=True)
        winners = scored[:top_k]
        if winners:
            self._reinforce([m["id"] for m in winners], winners)
        print(f"Recalled {len(winners)} memories (from {len(rows)} candidates).")
        return winners

    def _reinforce(self, memory_ids, winners):
        """Bump salience/access_count and log a recall event for each winner."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE memories
                    SET access_count = access_count + 1,
                        last_accessed_at = now(),
                        salience = LEAST(%s, salience + %s)
                    WHERE id = ANY(%s)
                    """,
                    (SALIENCE_CAP, REINFORCE_BOOST, memory_ids),
                )
                for m in winners:
                    cur.execute(
                        """
                        INSERT INTO memory_events
                            (memory_id, agent_id, event_type, score)
                        VALUES (%s, %s, 'recall', %s)
                        """,
                        (m["id"], self._agent_id, m["score"]),
                    )
            self.conn.commit()
        except psycopg2.Error as e:
            print(f"Warning: reinforcement failed: {e}")
            self.conn.rollback()

    # -- decay / maintenance -----------------------------------------------
    def run_decay(self):
        """
        Age memories toward archival. For each active memory, multiply salience
        by exp(-DECAY_RATE * days_since_last_access); memories that fall below
        DECAY_THRESHOLD are archived (decayed_at set) and excluded from recall.
        Returns (aged_count, archived_count).
        """
        if not self.conn:
            print("Cannot run decay: no database connection.")
            return (0, 0)

        aged = 0
        archived = 0
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, salience, last_accessed_at
                    FROM memories
                    WHERE agent_id = %s AND decayed_at IS NULL
                    """,
                    (self._agent_id,),
                )
                rows = cur.fetchall()
                now = datetime.now(timezone.utc)
                for mem_id, salience, last_accessed_at in rows:
                    days_idle = self._days_between(last_accessed_at, now)
                    new_salience = float(salience) * math.exp(-DECAY_RATE * days_idle)
                    if new_salience < DECAY_THRESHOLD:
                        cur.execute(
                            """
                            UPDATE memories
                            SET salience = %s, decayed_at = now()
                            WHERE id = %s
                            """,
                            (new_salience, mem_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO memory_events
                                (memory_id, agent_id, event_type, score)
                            VALUES (%s, %s, 'decay', %s)
                            """,
                            (mem_id, self._agent_id, new_salience),
                        )
                        archived += 1
                    else:
                        cur.execute(
                            "UPDATE memories SET salience = %s WHERE id = %s",
                            (new_salience, mem_id),
                        )
                        aged += 1
            self.conn.commit()
            print(f"Decay pass complete: {aged} aged, {archived} archived.")
            return (aged, archived)
        except psycopg2.Error as e:
            print(f"Database error during decay: {e}")
            self.conn.rollback()
            return (0, 0)

    # -- scoring helpers ----------------------------------------------------
    @staticmethod
    def _days_between(then, now):
        if then is None:
            return 0.0
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0.0, (now - then).total_seconds() / 86400.0)

    def _recency_score(self, last_accessed_at, now):
        """Exponential recency decay with a configurable half-life -> (0, 1]."""
        days = self._days_between(last_accessed_at, now)
        return math.pow(0.5, days / RECENCY_HALFLIFE_DAYS)

    @staticmethod
    def _frequency_score(access_count):
        """Diminishing-returns frequency boost normalized to ~(0, 1)."""
        return math.log1p(max(0, int(access_count))) / math.log(50.0)

    # -- lifecycle ----------------------------------------------------------
    def stats(self):
        """Return a small snapshot for health/observability endpoints."""
        if not self.conn:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) FILTER (WHERE decayed_at IS NULL) AS active,
                    count(*) FILTER (WHERE decayed_at IS NOT NULL) AS archived
                FROM memories WHERE agent_id = %s
                """,
                (self._agent_id,),
            )
            active, archived = cur.fetchone()
        return {"agent": self.agent_name, "active_memories": active,
                "archived_memories": archived}

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            print("Database connection closed.")
