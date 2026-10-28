"""On-disk storage for designer graphs: ``~/.hermes/workflow-designs/<name>.json``.

Names are restricted to ``[a-z0-9_.-]`` so a design name can never escape the store
root; ``loader`` code also re-validates the graph before writing.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


class DesignStore:
    """Saved designer graphs under ``$HERMES_HOME/workflow-designs/``."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else _hermes_home() / "workflow-designs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not _NAME_RE.match(name or ""):
            raise ValueError(
                f"bad design name {name!r}: use [a-z0-9_.-], start alnum, max 64 chars"
            )
        return self.root / f"{name}.json"

    def save(self, name: str, graph: dict) -> Path:
        from .schema import validate_designer_graph

        errors = validate_designer_graph(graph)
        if errors:
            first = errors[0]
            raise ValueError(
                f"invalid graph: {first['node']}:{first['field']}: {first['msg']}"
            )
        path = self._path(name)
        path.write_text(json.dumps(graph, indent=2) + "\n")
        return path

    def load(self, name: str) -> dict:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"no saved workflow named {name!r}")
        return json.loads(path.read_text())

    def list_designs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))


_RUN_ID_RE = re.compile(r"^[a-f0-9]{6,32}$")


class RunStore:
    """Paused/complete run state under ``$HERMES_HOME/workflow-runs/<run_id>.json``.

    Run ids are generated as ``uuid4().hex[:12]``; the pattern is enforced so a caller cannot
    address a path outside the store root.
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else _hermes_home() / "workflow-runs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not _RUN_ID_RE.match(run_id or ""):
            raise ValueError(f"bad run id {run_id!r}")
        return self.root / f"{run_id}.json"

    def save(self, state: dict) -> Path:
        path = self._path(state["run_id"])
        path.write_text(json.dumps(state, indent=2) + "\n")
        return path

    def load(self, run_id: str) -> dict:
        path = self._path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"no run {run_id!r}")
        return json.loads(path.read_text())

    def list_runs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))
