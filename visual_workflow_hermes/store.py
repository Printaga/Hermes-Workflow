"""On-disk storage for designer graphs: ``~/.hermes/workflow-designs/<name>.json``.

Names are restricted to ``[a-z0-9_.-]`` so a design name can never escape the store
root; ``loader`` code also re-validates the graph before writing.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _write_json(path: Path, payload) -> None:
    """Write JSON atomically: a reader never sees a truncated file.

    ``write_text`` truncates before streaming, and the canvas polls the run store while the
    runner saves on every step, so a torn read is a real (not theoretical) race. The temp
    file lives in the destination directory so ``os.replace`` stays atomic.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class DesignStore:
    """Saved designer graphs under ``$HERMES_HOME/workflow-designs/``."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else _hermes_home() / "workflow-designs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        # JSON is untyped: a number/object here is a bad name, not a TypeError from re.match.
        if not isinstance(name, str) or not _NAME_RE.match(name):
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
        _write_json(path, graph)
        return path

    def load(self, name: str) -> dict:
        path = self._path(name)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError(f"no saved workflow named {name!r}") from None
        except (OSError, ValueError) as exc:
            raise ValueError(f"corrupt workflow file {name!r}: {exc}") from exc

    def list_designs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

    def delete(self, name: str) -> None:
        path = self._path(name)
        try:
            path.unlink()
        except FileNotFoundError:
            raise FileNotFoundError(f"no saved workflow named {name!r}") from None


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
        # A non-string id (e.g. a number from a hand-written tool argument) is a bad id, not
        # a TypeError escaping the store's ValueError contract.
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            raise ValueError(f"bad run id {run_id!r}")
        return self.root / f"{run_id}.json"

    def save(self, state: dict) -> Path:
        run_id = state.get("run_id") if isinstance(state, dict) else None
        if not isinstance(run_id, str):  # KeyError/TypeError would break the ValueError contract
            raise ValueError(f"run state has no valid run_id: {run_id!r}")
        path = self._path(run_id)
        _write_json(path, state)
        return path

    def load(self, run_id: str) -> dict:
        path = self._path(run_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError(f"no run {run_id!r}") from None
        except (OSError, ValueError) as exc:
            raise ValueError(f"corrupt run file {run_id!r}: {exc}") from exc

    def list_runs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

    def delete(self, run_id: str) -> None:
        path = self._path(run_id)
        try:
            path.unlink()
        except FileNotFoundError:
            raise FileNotFoundError(f"no run {run_id!r}") from None

    def recent(self, limit: int = 20) -> list[dict]:
        """Newest-first runs: ``[{run_id, updated, state}]``; unreadable files are skipped.

        The Runs list needs every run on disk, not just the one this session started, so a
        run begun by the chat tool or a cron job is visible in the canvas too.
        """
        rows: list[dict] = []
        for path in self.root.glob("*.json"):
            if not _RUN_ID_RE.match(path.stem):
                continue
            try:
                state = json.loads(path.read_text())
                updated = path.stat().st_mtime
            except (OSError, ValueError):  # a half-written or corrupt file is not a run
                continue
            if isinstance(state, dict) and isinstance(state.get("status"), str):
                rows.append({"run_id": path.stem, "updated": updated, "state": state})
        rows.sort(key=lambda row: row["updated"], reverse=True)
        return rows[: max(0, int(limit))]
