"""Read the DEPLOYED plugin's GET /runs handler against the real run store."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

DEPLOYED = Path.home() / ".hermes" / "plugins" / "visual-workflow" / "dashboard" / "plugin_api.py"
print("deployed api:", DEPLOYED, "| exists:", DEPLOYED.is_file())

spec = importlib.util.spec_from_file_location("deployed_plugin_api", DEPLOYED)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

rows = mod.list_runs(limit=10)["runs"]
print("runs listed:", len(rows))
for row in rows:
    print(
        f"  {row['run_id']}  {row['status']:<18} name={row['name']!r} "
        f"node={row['node_id']!r} options={row['options']} updated={int(row['updated'])}"
    )

known = {r["run_id"]: r for r in rows}
for run_id in ("c52f4a0600dd", "714f7c646491"):
    print(run_id, "->", json.dumps(known.get(run_id, "not in the last 10"))[:200])
