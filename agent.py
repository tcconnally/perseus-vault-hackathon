"""
Perseus Vault agent — OpenAI embedding provider.

Thin subclass of PerseusVaultCore that supplies embeddings via the OpenAI API.
All storage / recall-ranking / decay logic lives in vault_core.py.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

from vault_core import PerseusVaultCore

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Retained for the optional ccloud health check / stats endpoints.
CCLOUD_CLUSTER_NAME = os.getenv("CCLOUD_CLUSTER_NAME")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
# text-embedding-3-small is 1536-d natively; keep EMBEDDING_DIMENSION in sync
# with the schema (db_schema.py) and .env.
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1536"))
AGENT_ID = os.getenv("AGENT_ID", "perseus-vault-demo-openai")


class PerseusAgent(PerseusVaultCore):
    def __init__(self, db_url, cluster_name=None, agent_name=AGENT_ID):
        self.cluster_name = cluster_name
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        super().__init__(db_url, agent_name)

    def _get_embedding(self, text: str):
        try:
            resp = self.client.embeddings.create(
                input=[text], model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSION
            )
            return resp.data[0].embedding
        except Exception as e:
            print(f"Error: OpenAI embedding failed. {e}")
            return None


if __name__ == "__main__":
    if not all([DATABASE_URL, OPENAI_API_KEY]):
        print("Missing env: set DATABASE_URL and OPENAI_API_KEY (see .env.example).")
    else:
        agent = PerseusAgent(DATABASE_URL, CCLOUD_CLUSTER_NAME)
        print("\n--- STEP 1: ADDING MEMORY (OpenAI) ---")
        agent.add_memory(
            "The deployment target for project Phoenix is AWS Lambda in us-east-1.",
            metadata={"project": "phoenix", "type": "infra"},
        )
        print("\n--- STEP 2: RECALLING MEMORY (OpenAI) ---")
        for mem in agent.recall_memories("What is the deployment region for Phoenix?"):
            print(f"  - {mem['content']} "
                  f"(score={mem['score']}, sim={mem['similarity']})")
        agent.close()
