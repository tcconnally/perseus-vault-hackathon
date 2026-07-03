import os
import psycopg2
from dotenv import load_dotenv

def create_schema():
    """
    Connects to the CockroachDB cluster and creates the necessary
    table for the Perseus Vault agent memory if it doesn't already exist.
    """
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        print("Error: DATABASE_URL environment variable not set.")
        print("Please create a .env file with your CockroachDB connection string.")
        return

    conn = None
    try:
        print("Connecting to the database...")
        conn = psycopg2.connect(db_url)
        print("Connection successful.")

        with conn.cursor() as cur:
            # Note: The CLUSTER SETTING is a one-time operation for the cluster
            # and does not need to be run by the application.
            # SET CLUSTER SETTING feature.vector_index.enabled = true;
            
            # Get embedding dimension from environment variable, default to 1024 for Bedrock
            dimension = os.getenv("EMBEDDING_DIMENSION", "1024")
            print(f"Creating 'vault_entries' table with dimension {dimension} if it doesn't exist...")
            
            # Using vector_cosine_ops for semantic similarity searches
            create_table_query = f"""
            CREATE TABLE IF NOT EXISTS vault_entries (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_id STRING NOT NULL,
                content STRING NOT NULL,
                embedding VECTOR({dimension}),
                created_at TIMESTAMPTZ DEFAULT now(),
                VECTOR INDEX embed_idx (embedding vector_cosine_ops)
            );
            """
            cur.execute(create_table_query)
            conn.commit()
            print("Table 'vault_entries' is ready.")

    except psycopg2.Error as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()
            print("Connection closed.")

if __name__ == "__main__":
    create_schema()
