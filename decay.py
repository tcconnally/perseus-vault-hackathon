"""
Perseus Vault — decay maintenance runner.

Runs one time-based decay pass over an agent's memories: salience is aged by
time-since-last-access and low-salience memories are archived out of the active
recall set. Intended to be invoked on a schedule (e.g. Amazon EventBridge ->
Lambda, or cron) so the working memory set stays signal-dense over time.

Usage:  python decay.py
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _make_agent():
    """Reuse the same provider selection as the request handlers."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL not set (see .env.example).")
    try:
        from bedrock_agent import PerseusAgentBedrock, AWS_REGION, CCLOUD_CLUSTER_NAME
        return PerseusAgentBedrock(db_url, CCLOUD_CLUSTER_NAME, AWS_REGION)
    except Exception as e:
        print(f"Bedrock unavailable ({e}); using OpenAI provider.")
        from agent import PerseusAgent, CCLOUD_CLUSTER_NAME
        return PerseusAgent(db_url, CCLOUD_CLUSTER_NAME)


def main():
    agent = _make_agent()
    print("Vault before:", agent.stats())
    aged, archived = agent.run_decay()
    print(f"Decay pass: aged={aged}, archived={archived}")
    print("Vault after:", agent.stats())
    agent.close()


if __name__ == "__main__":
    main()
