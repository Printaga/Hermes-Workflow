"""Throwaway server for the live approval-gate HTTP check (not shipped, not a test)."""
import sys

sys.path.insert(0, "/home/lenovo/Development/Hermes-Workflow")
sys.path.insert(0, "/home/lenovo/.hermes/hermes-agent")

import uvicorn
from fastapi import FastAPI

from dashboard.plugin_api import router

app = FastAPI()
app.include_router(router, prefix="/api/plugins/visual-workflow")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8799, log_level="warning")
