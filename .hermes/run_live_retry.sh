#!/usr/bin/env bash
# Launches the live retry probe server through uv so fastapi/uvicorn exist (not shipped).
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --isolated --no-project \
  --with 'fastapi>=0.115,<1' --with 'uvicorn>=0.30,<1' \
  --with 'httpx>=0.27,<1' --with 'ruamel.yaml>=0.18,<1' \
  python3 .hermes/live_retry_server.py "$@"
