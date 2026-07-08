"""
Perseus Vault — distributed CockroachDB schema.

Relational, event-sourced agentic-memory model (not a flat key-value table):

  agents          identity anchor for cross-session persistence
  memories        content + JSONB metadata + VECTOR embedding + decay state,
                  FK -> agents (ON DELETE CASCADE)
  memory_events   append-only, timestamped log of store/recall/decay/reinforce
                  events, FK -> memories and agents

Distributed features exercised:
  * VECTOR column + C-SPANN cosine vector index for ANN similarity search
    that scales horizontally across the CockroachDB cluster.
  * INVERTED INDEX on JSONB metadata for flexible attribute filtering.
  * Foreign keys with cascade, enforced across ranges/nodes.
  * Optional multi-region survivability (see MULTI_REGION_SQL below).

Run once against your cluster:  python db_schema.py
"""

import os

import psycopg2
from dotenv import load_dotenv


def build_schema_sql(dimension: int) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS agents (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name       STRING NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS memories (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        agent_id         UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        content          STRING NOT NULL,
        metadata         JSONB NOT NULL DEFAULT '{{}}'::JSONB,
        embedding        VECTOR({dimension}),
        salience         FLOAT NOT NULL DEFAULT 1.0,
        access_count     INT NOT NULL DEFAULT 0,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        decayed_at       TIMESTAMPTZ,
        INDEX idx_mem_agent (agent_id),
        INVERTED INDEX idx_mem_metadata (metadata),
        VECTOR INDEX idx_mem_embedding (embedding vector_cosine_ops)
    );

    CREATE TABLE IF NOT EXISTS memory_events (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        memory_id   UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        event_type  STRING NOT NULL,
        score       FLOAT,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        INDEX idx_evt_memory (memory_id, occurred_at),
        INDEX idx_evt_agent_time (agent_id, occurred_at)
    );
    """


# Optional: promote the database to multi-region for zone/region survivability.
# Requires a multi-region CockroachDB cluster; run manually if desired.
MULTI_REGION_SQL = """
-- ALTER DATABASE defaultdb PRIMARY REGION "us-east-1";
-- ALTER DATABASE defaultdb ADD REGION "us-west-2";
-- ALTER DATABASE defaultdb SURVIVE REGION FAILURE;
-- ALTER TABLE memories SET LOCALITY REGIONAL BY ROW;
-- ALTER TABLE memory_events SET LOCALITY REGIONAL BY ROW;
"""


def create_schema():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set. Create a .env from .env.example.")
        return

    dimension = int(os.getenv("EMBEDDING_DIMENSION", "1024"))
    conn = None
    try:
        print("Connecting to CockroachDB...")
        conn = psycopg2.connect(db_url)
        print(f"Connected. Creating relational schema (VECTOR dim={dimension})...")
        with conn.cursor() as cur:
            # C-SPANN vector indexes require this cluster setting (one-time; needs
            # admin). Attempt it, but don't fail the whole run if unprivileged.
            try:
                cur.execute("SET CLUSTER SETTING feature.vector_index.enabled = true;")
                conn.commit()
            except psycopg2.Error as e:
                conn.rollback()
                print(f"Note: could not set vector_index cluster setting ({e}). "
                      "Ask a cluster admin to enable it if index creation fails.")
            cur.execute(build_schema_sql(dimension))
        conn.commit()
        print("Schema ready: agents, memories, memory_events.")
        print("Multi-region survivability is available (see MULTI_REGION_SQL).")
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Connection closed.")


if __name__ == "__main__":
    create_schema()
