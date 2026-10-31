"""Read the DEPLOYED plugin's GET /runs handler against the real run store."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
DEPLOYED = HOME / "plugins" / "visual-workflow" / "dashboard" / "plugin_api.py"
print("deployed api:", DEPLOYED, "| exists:", DEPLOYED.is_file())

if not DEPLOYED.is_file():
    print(f"deployed plugin not found: {DEPLOYED}", file=sys.stderr)
    raise SystemExit(1)
spec = importlib.util.spec_from_file_location("deployed_plugin_api", DEPLOYED)
if spec is None or spec.loader is None:
    print(f"cannot create an import spec for: {DEPLOYED}", file=sys.stderr)
    raise SystemExit(1)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

payload = mod.list_runs(limit=10)
if not isinstance(payload, dict) or not isinstance(payload.get("runs"), list):
    print(f"unexpected list_runs response: {payload!r:.500}", file=sys.stderr)
    raise SystemExit(1)

rows = payload["runs"]
print("runs listed:", len(rows))
known = {}
for row in rows:
    if not isinstance(row, dict):
        print(f"skipping non-object row: {row!r:.200}", file=sys.stderr)
        continue
    try:
        print(
            f"  {row['run_id']}  {row['status']:<18} name={row['name']!r} "
            f"node={row['node_id']!r} options={row.get('options')} updated={int(row['updated'])}"
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(f"skipping malformed row {row!r:.300}: {exc}", file=sys.stderr)
        continue
    known[row["run_id"]] = row

for run_id in ("c52f4a0600dd", "714f7c646491"):
    print(run_id, "->", json.dumps(known.get(run_id, "not in the last 10"))[:200])
