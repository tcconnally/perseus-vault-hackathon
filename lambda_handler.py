"""
AWS Lambda handler for Perseus Vault.

Routes API Gateway (HTTP API / Lambda function URL) events to the agent.
The agent is initialized once per execution environment and reused across warm
invocations; state lives entirely in CockroachDB, so cold starts lose nothing.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(__file__))

agent = None
provider = None


def _json(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=str),
    }


def _init_agent():
    global agent, provider
    if agent is not None:
        return
    # Bedrock is the primary AWS path; OpenAI is the fallback.
    try:
        from bedrock_agent import (PerseusAgentBedrock, DATABASE_URL,
                                   CCLOUD_CLUSTER_NAME, AWS_REGION)
        agent = PerseusAgentBedrock(DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION)
        provider = "Bedrock"
        print(f"INIT: Bedrock agent ready (region={AWS_REGION})")
        return
    except Exception as e:
        print(f"INIT: Bedrock failed ({type(e).__name__}: {e}); trying OpenAI...")
    try:
        from agent import PerseusAgent, DATABASE_URL, CCLOUD_CLUSTER_NAME
        agent = PerseusAgent(DATABASE_URL, CCLOUD_CLUSTER_NAME)
        provider = "OpenAI"
        print("INIT: OpenAI agent ready")
    except Exception:
        print(f"INIT: both providers failed:\n{traceback.format_exc()}")


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
        return _json(200, {
            "name": "Perseus-Vault",
            "status": "running" if agent else "degraded",
            "provider": provider,
            "endpoints": {
                "POST /remember": "Store a memory {content, metadata?}",
                "POST /recall": "Recall memories {query, top_k?}",
                "POST /decay": "Run a decay maintenance pass",
                "GET /health": "Health + vault stats",
            },
        })

    if path == "/health" and method == "GET":
        if agent is None:
            return _json(503, {"status": "unhealthy", "error": "Agent not initialized"})
        return _json(200, {"status": "healthy", "provider": provider,
                           "vault": agent.stats()})

    if agent is None:
        return _json(503, {"error": "Agent not initialized"})

    if path == "/remember" and method == "POST":
        content = body.get("content", "")
        if not content:
            return _json(400, {"error": "Missing 'content'"})
        memory_id = agent.add_memory(content, body.get("metadata"))
        return _json(200, {"status": "stored", "id": memory_id, "content": content})

    if path == "/recall" and method == "POST":
        query = body.get("query", "")
        if not query:
            return _json(400, {"error": "Missing 'query'"})
        memories = agent.recall_memories(query, body.get("top_k", 3))
        return _json(200, {"query": query, "memories": memories})

    if path == "/decay" and method == "POST":
        aged, archived = agent.run_decay()
        return _json(200, {"status": "ok", "aged": aged, "archived": archived})

    return _json(404, {"error": f"Not found: {method} {path}"})
