"""
Flask HTTP wrapper for Perseus-Vault agent.
Provides a live REST API for the hackathon demo.
"""
import os
import sys
import json
import subprocess
from flask import Flask, request, jsonify

# Import the agent class
sys.path.insert(0, os.path.dirname(__file__))

app = Flask(__name__)

# Try Bedrock agent first, fall back to OpenAI
try:
    from bedrock_agent import PerseusAgentBedrock, DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION
    agent = PerseusAgentBedrock(DATABASE_URL, CCLOUD_CLUSTER_NAME, AWS_REGION)
    provider = "Bedrock"
except Exception as e:
    try:
        from agent import PerseusAgent, DATABASE_URL, CCLOUD_CLUSTER_NAME
        agent = PerseusAgent(DATABASE_URL, CCLOUD_CLUSTER_NAME)
        provider = "OpenAI"
    except Exception as e2:
        print(f"Could not initialize agent: {e2}")
        agent = None
        provider = None


@app.route("/")
def index():
    return jsonify({
        "name": "Perseus-Vault",
        "status": "running" if agent else "degraded",
        "provider": provider,
        "endpoints": {
            "POST /remember": "Store a memory",
            "POST /recall": "Recall memories by query",
            "GET /health": "Health check"
        }
    })


@app.route("/health")
def health():
    if agent is None:
        return jsonify({"status": "unhealthy", "error": "Agent not initialized"}), 503
    healthy = agent._is_cluster_healthy()
    return jsonify({
        "status": "healthy" if healthy else "degraded",
        "cluster": CCLOUD_CLUSTER_NAME,
        "provider": provider
    })


@app.route("/remember", methods=["POST"])
def remember():
    if agent is None:
        return jsonify({"error": "Agent not initialized"}), 503

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field in JSON body"}), 400

    content = data["content"]
    agent.add_memory(content)
    return jsonify({
        "status": "stored",
        "content": content
    })


@app.route("/recall", methods=["POST"])
def recall():
    if agent is None:
        return jsonify({"error": "Agent not initialized"}), 503

    data = request.get_json()
    if not data or "query" not in data:
        return jsonify({"error": "Missing 'query' field in JSON body"}), 400

    query = data["query"]
    top_k = data.get("top_k", 3)
    memories = agent.recall_memories(query, top_k)
    return jsonify({
        "query": query,
        "memories": memories
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Perseus-Vault on port {port}...")
    print(f"Provider: {provider}")
    app.run(host="0.0.0.0", port=port)
