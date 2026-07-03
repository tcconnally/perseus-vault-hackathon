"""
AWS Lambda handler for Perseus-Vault.
Receives API Gateway events and routes to agent.
"""
import os
import json
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

agent = None
provider = None


def _init_agent():
    global agent, provider
    if agent is not None:
        return

    # Try OpenAI first (no rate limit issues on free tier)
    try:
        from agent import PerseusAgent, DATABASE_URL, CCLOUD_CLUSTER_NAME
        agent = PerseusAgent(DATABASE_URL, CCLOUD_CLUSTER_NAME)
        provider = "OpenAI"
        print(f"INIT: OpenAI agent ready, cluster={CCLOUD_CLUSTER_NAME}")
        return
    except Exception as e:
        print(f"INIT: OpenAI failed ({type(e).__name__}: {e}), trying Bedrock...")

    try:
        from bedrock_agent import PerseusAgentBedrock, DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION
        agent = PerseusAgentBedrock(DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION)
        provider = "Bedrock"
        print(f"INIT: Bedrock agent ready, cluster={CCLOUD_CLUSTER_NAME}")
    except Exception as e2:
        print(f"INIT: Bedrock also failed: {traceback.format_exc()}")
        agent = None
        provider = None


def handler(event, context):
    _init_agent()

    path = event.get("rawPath", "/")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    body = {}

    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except json.JSONDecodeError:
            pass

    if path == "/" and method == "GET":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "name": "Perseus-Vault",
                "status": "running" if agent else "degraded",
                "provider": provider,
                "endpoints": {
                    "POST /remember": "Store a memory",
                    "POST /recall": "Recall memories by query"
                }
            })
        }

    if path == "/remember" and method == "POST":
        if agent is None:
            return {"statusCode": 503, "body": json.dumps({"error": "Agent not initialized"})}
        content = body.get("content", "")
        if not content:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing 'content'"})}
        agent.add_memory(content)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "stored", "content": content})
        }

    if path == "/recall" and method == "POST":
        if agent is None:
            return {"statusCode": 503, "body": json.dumps({"error": "Agent not initialized"})}
        query = body.get("query", "")
        if not query:
            return {"statusCode": 400, "body": json.dumps({"error": "Missing 'query'"})}
        top_k = body.get("top_k", 3)
        memories = agent.recall_memories(query, top_k)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"query": query, "memories": memories})
        }

    return {
        "statusCode": 404,
        "body": json.dumps({"error": f"Not found: {method} {path}"})
    }
