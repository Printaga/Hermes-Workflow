"""Throwaway server for the live retry-path check (not shipped, not a test).

Serves the *deployed* plugin copy: its root goes first on sys.path so the host serves exactly
what ~/.hermes/plugins/visual-workflow contains after the disable/enable rebuild.
"""
import sys

DEPLOYED = "/home/lenovo/.hermes/plugins/visual-workflow"
sys.path.insert(0, DEPLOYED)                      # deployed copy first
sys.path.insert(0, "/home/lenovo/Development/Hermes-Workflow")
sys.path.insert(0, "/home/lenovo/.hermes/hermes-agent")

import uvicorn
from fastapi import FastAPI

from dashboard.plugin_api import router

app = FastAPI()
app.include_router(router, prefix="/api/plugins/visual-workflow")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8797, log_level="warning")
