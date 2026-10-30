#!/usr/bin/env bash
# Launches the live retry probe server through uv so fastapi/uvicorn exist (not shipped).
cd /home/lenovo/Development/Hermes-Workflow
exec uv run --isolated --no-project \
  --with fastapi --with uvicorn --with httpx --with ruamel-yaml \
  python3 .hermes/live_retry_server.py
