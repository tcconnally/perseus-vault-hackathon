import os
import json
import subprocess
import psycopg2
import openai
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# This should be your cluster's name in CockroachDB Cloud
CCLOUD_CLUSTER_NAME = os.getenv("CCLOUD_CLUSTER_NAME") 
AGENT_ID = "perseus-vault-demo-v1"
EMBEDDING_MODEL = "text-embedding-3-small" # 1536 dimensions
EMBEDDING_DIMENSION = os.getenv("EMBEDDING_DIMENSION", "1536") # Default for OpenAI
EMBEDDING_DIMENSION = os.getenv("EMBEDDING_DIMENSION", "1536") # Default to OpenAI's dimension

# Set OpenAI Key
openai.api_key = OPENAI_API_KEY

class PerseusAgent:
    def __init__(self, db_url, cluster_name):
        self.db_url = db_url
        self.cluster_name = cluster_name
        self.conn = None
        self._connect_db()

    def _connect_db(self):
        """Initializes the database connection."""
        try:
            self.conn = psycopg2.connect(self.db_url)
        except psycopg2.Error as e:
            print(f"Error: Could not connect to the database. {e}")
            self.conn = None

    def _get_embedding(self, text: str):
        """Generates an embedding for the given text using OpenAI."""
        try:
            response = openai.Embedding.create(input=[text], model=EMBEDDING_MODEL)
            return response['data'][0]['embedding']
        except Exception as e:
            print(f"Error: Failed to get embedding from OpenAI. {e}")
            return None

    def _is_cluster_healthy(self) -> bool:
        """
        Uses the ccloud CLI to perform a health check on the cluster.
        Returns True if the cluster state is CREATED, False otherwise.
        """
        if not self.cluster_name:
            print("Error: CCLOUD_CLUSTER_NAME environment variable not set. Skipping health check.")
            return False
            
        print(f"Running health check on cluster '{self.cluster_name}'...")
        try:
            command = ["ccloud", "cluster", "info", self.cluster_name]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            
            # Parse plain text output for robustness, as JSON flag is unconfirmed.
            if "CLUSTER_STATE_CREATED" in result.stdout:
                print("Health check PASSED. Cluster is in CREATED state.")
                return True
            else:
                print(f"Health check FAILED. Cluster state is not CREATED. Output:\n{result.stdout}")
                return False
        except FileNotFoundError:
            print("Error: 'ccloud' command not found. Is the ccloud CLI installed and in your PATH?")
            return False
        except subprocess.CalledProcessError as e:
            print(f"Error executing ccloud CLI: {e}")
            print(f"Stderr: {e.stderr}")
            return False
        except json.JSONDecodeError:
            print("Error: Failed to parse JSON output from ccloud CLI.")
            return False


    def add_memory(self, content: str):
        """
        Adds a new memory to the vault. Performs a health check first.
        """
        if not self.conn:
            print("Cannot add memory: Database connection is not available.")
            return

        if not self._is_cluster_healthy():
            print("Aborting memory write due to cluster health check failure.")
            return

        print(f"Generating embedding for: '{content}'")
        embedding = self._get_embedding(content)

        if embedding is None:
            print("Could not generate embedding. Aborting memory write.")
            return

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO vault_entries (agent_id, content, embedding) VALUES (%s, %s, %s)",
                    (AGENT_ID, content, embedding)
                )
                self.conn.commit()
                print("Successfully added new memory to the Perseus Vault.")
        except psycopg2.Error as e:
            print(f"Database error during memory insert: {e}")
            self.conn.rollback()


    def recall_memories(self, query: str, top_k: int = 3):
        """
        Recalls the most relevant memories from the vault based on a query.
        """
        if not self.conn:
            print("Cannot recall memories: Database connection is not available.")
            return []

        print(f"Recalling memories related to: '{query}'")
        query_embedding = self._get_embedding(query)

        if query_embedding is None:
            print("Could not generate query embedding. Aborting recall.")
            return []

        try:
            with self.conn.cursor() as cur:
                # Note: psycopg2 automatically handles list-to-vector-string conversion.
                cur.execute(
                    """
                    SELECT id, content, created_at, embedding <-> %s AS distance
                    FROM vault_entries
                    WHERE agent_id = %s
                    ORDER BY distance
                    LIMIT %s
                    """,
                    (query_embedding, AGENT_ID, top_k)
                )
                results = cur.fetchall()
                memories = [
                    {"id": row[0], "content": row[1], "timestamp": row[2], "distance": row[3]}
                    for row in results
                ]
                print(f"Found {len(memories)} relevant memories.")
                return memories
        except psycopg2.Error as e:
            print(f"Database error during memory recall: {e}")
            return []

    def close(self):
        if self.conn:
            self.conn.close()
            print("Database connection closed.")


if __name__ == '__main__':
    # --- Demo Script ---
    if not all([DATABASE_URL, OPENAI_API_KEY, CCLOUD_CLUSTER_NAME]):
        print("Error: Missing one or more environment variables.")
        print("Please ensure DATABASE_URL, OPENAI_API_KEY, and CCLOUD_CLUSTER_NAME are set in your .env file.")
    else:
        agent = PerseusAgent(DATABASE_URL, CCLOUD_CLUSTER_NAME)
        
        # Part 1: Add a memory
        print("\n--- STEP 1: ADDING MEMORY ---")
        memory_to_add = "The deployment target for project Phoenix is AWS Lambda in the us-east-1 region."
        agent.add_memory(memory_to_add)

        # Part 2: Recall the memory
        print("\n--- STEP 2: RECALLING MEMORY ---")
        query = "What is the deployment region for Phoenix?"
        recalled = agent.recall_memories(query)

        if recalled:
            print("\nTop recalled memories:")
            for mem in recalled:
                print(f"  - [Content]: {mem['content']} (Distance: {mem['distance']:.4f})")
        
        agent.close()
