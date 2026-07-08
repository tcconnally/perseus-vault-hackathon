"""
Flask HTTP wrapper for the Perseus Vault agent — a live REST API for the demo.

Endpoints:
  GET  /          service banner
  GET  /health    agent + vault stats
  POST /remember  {"content": "...", "metadata": {...}}
  POST /recall    {"query": "...", "top_k": 3}
  POST /decay     run a decay/maintenance pass
"""

import os
import sys

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)

# Prefer the Bedrock (AWS) provider; fall back to OpenAI if unavailable.
agent = None
provider = None
try:
    from bedrock_agent import (PerseusAgentBedrock, DATABASE_URL,
                               CCLOUD_CLUSTER_NAME, AWS_REGION)
    agent = PerseusAgentBedrock(DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION)
    provider = "Bedrock"
except Exception as e:
    print(f"Bedrock init failed ({e}); trying OpenAI...")
    try:
        from agent import PerseusAgent, DATABASE_URL, CCLOUD_CLUSTER_NAME
        agent = PerseusAgent(DATABASE_URL, CCLOUD_CLUSTER_NAME)
        provider = "OpenAI"
    except Exception as e2:
        print(f"Could not initialize agent: {e2}")


@app.route("/")
def index():
    return jsonify({
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


@app.route("/health")
def health():
    if agent is None:
        return jsonify({"status": "unhealthy", "error": "Agent not initialized"}), 503
    return jsonify({"status": "healthy", "provider": provider, "vault": agent.stats()})


@app.route("/remember", methods=["POST"])
def remember():
    if agent is None:
        return jsonify({"error": "Agent not initialized"}), 503
    data = request.get_json(silent=True) or {}
    if "content" not in data:
        return jsonify({"error": "Missing 'content'"}), 400
    memory_id = agent.add_memory(data["content"], data.get("metadata"))
    return jsonify({"status": "stored", "id": str(memory_id), "content": data["content"]})


@app.route("/recall", methods=["POST"])
def recall():
    if agent is None:
        return jsonify({"error": "Agent not initialized"}), 503
    data = request.get_json(silent=True) or {}
    if "query" not in data:
        return jsonify({"error": "Missing 'query'"}), 400
    memories = agent.recall_memories(data["query"], data.get("top_k", 3))
    for m in memories:  # make UUID/datetime JSON-safe
        m["id"] = str(m["id"])
        m["created_at"] = m["created_at"].isoformat()
        m["last_accessed_at"] = m["last_accessed_at"].isoformat()
    return jsonify({"query": data["query"], "memories": memories})


@app.route("/decay", methods=["POST"])
def decay():
    if agent is None:
        return jsonify({"error": "Agent not initialized"}), 503
    aged, archived = agent.run_decay()
    return jsonify({"status": "ok", "aged": aged, "archived": archived})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Perseus-Vault on port {port} (provider={provider})...")
    app.run(host="0.0.0.0", port=port)
