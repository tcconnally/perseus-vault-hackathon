"""
Preflight verifier for the CockroachDB MCP Server integration.

This does NOT invent a fake MCP session. It checks that the pieces required to
launch the official CockroachDB MCP Server (github.com/amineelkouhen/mcp-cockroachdb)
are actually present and consistent with this repo's config, then prints the exact
launch command your MCP client will run.

What it verifies:
  1. `uvx` (from the `uv` toolchain) is installed and on PATH.
  2. mcp_config.json exists and references the official server.
  3. The CRDB_* connection env vars needed by the MCP server are set.

Usage:  python verify_mcp.py
"""

import json
import os
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()

REQUIRED_ENV = ["CRDB_HOST", "CRDB_PORT", "CRDB_DATABASE", "CRDB_USERNAME"]
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "mcp_config.json")


def main():
    ok = True

    uvx = shutil.which("uvx")
    if uvx:
        print(f"[ok]   uvx found: {uvx}")
    else:
        ok = False
        print("[FAIL] uvx not found. Install uv: https://docs.astral.sh/uv/  "
              "(the MCP server launches via `uvx`).")

    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        server = cfg["mcpServers"]["cockroachdb"]
        args = " ".join(server["args"])
        assert "amineelkouhen/mcp-cockroachdb" in args
        print(f"[ok]   mcp_config.json references the official CockroachDB MCP Server")
    except (OSError, KeyError, AssertionError) as e:
        ok = False
        print(f"[FAIL] mcp_config.json missing or malformed: {e}")

    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    if missing:
        ok = False
        print(f"[FAIL] missing CRDB env vars: {', '.join(missing)} "
              "(copy .env.example -> .env and fill them in).")
    else:
        print(f"[ok]   CRDB connection env vars present ({', '.join(REQUIRED_ENV)})")

    print("\nLaunch command the MCP client will run:")
    print("  uvx --from git+https://github.com/amineelkouhen/mcp-cockroachdb.git "
          "cockroachdb-mcp-server")

    if ok:
        print("\nAll preflight checks passed. Load mcp_config.json into your MCP "
              "client to query the Perseus Vault cluster in natural language.")
    else:
        print("\nOne or more checks failed — see [FAIL] lines above.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
