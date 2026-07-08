"""
Perseus Vault agent — Amazon Bedrock embedding provider (primary AWS path).

Thin subclass of PerseusVaultCore that supplies embeddings via Amazon Bedrock
(Titan Text Embeddings V2). All storage / recall-ranking / decay logic lives in
vault_core.py. This is the variant deployed to AWS Lambda.
"""

import json
import os

import boto3
from dotenv import load_dotenv

from vault_core import PerseusVaultCore

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CCLOUD_CLUSTER_NAME = os.getenv("CCLOUD_CLUSTER_NAME")
EMBEDDING_MODEL_ID = os.getenv("BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1024"))  # Titan v2 default
AGENT_ID = os.getenv("AGENT_ID", "perseus-vault-demo-bedrock")


class PerseusAgentBedrock(PerseusVaultCore):
    def __init__(self, db_url, cluster_name=None, region=AWS_REGION, agent_name=AGENT_ID):
        self.cluster_name = cluster_name
        self.bedrock = boto3.client(service_name="bedrock-runtime", region_name=region)
        super().__init__(db_url, agent_name)

    def _get_embedding(self, text: str):
        try:
            body = json.dumps({
                "inputText": text,
                "dimensions": EMBEDDING_DIMENSION,
                "normalize": True,
            })
            resp = self.bedrock.invoke_model(
                body=body,
                modelId=EMBEDDING_MODEL_ID,
                accept="application/json",
                contentType="application/json",
            )
            return json.loads(resp["body"].read())["embedding"]
        except Exception as e:
            print(f"Error: Bedrock embedding failed. {e}")
            return None


if __name__ == "__main__":
    if not DATABASE_URL:
        print("Missing env: set DATABASE_URL (see .env.example).")
    else:
        agent = PerseusAgentBedrock(DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION)
        print("\n--- STEP 1: ADDING MEMORY (Bedrock) ---")
        agent.add_memory(
            "The primary contact for the Cerberus project is Dr. Aris Thorne.",
            metadata={"project": "cerberus", "type": "contact"},
        )
        print("\n--- STEP 2: RECALLING MEMORY (Bedrock) ---")
        for mem in agent.recall_memories("Who is the main contact for project Cerberus?"):
            print(f"  - {mem['content']} "
                  f"(score={mem['score']}, sim={mem['similarity']})")
        agent.close()
