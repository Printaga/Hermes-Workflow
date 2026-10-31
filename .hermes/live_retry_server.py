"""Throwaway server for the live retry-path check (not shipped, not a test).

Serves the *deployed* plugin copy: its root must end up first on sys.path so the host serves
exactly what ~/.hermes/plugins/visual-workflow contains after the disable/enable rebuild.
"""
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
DEPLOYED = HOME / "plugins" / "visual-workflow"
REPO = Path(__file__).resolve().parents[1]

# insert(0, ...) pushes earlier entries down, so the deployed copy is inserted LAST to win.
sys.path.insert(0, str(HOME / "hermes-agent"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(DEPLOYED))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from dashboard.plugin_api import router  # noqa: E402

app = FastAPI()
app.include_router(router, prefix="/api/plugins/visual-workflow")

if __name__ == "__main__":
    port = int(os.environ.get("PROBE_PORT") or 8797)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
