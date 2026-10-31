# Testing

The suite is pure Python and runs in seconds: 400+ pytest cases covering the schema, stores,
converter, runner, routes, canvases, widget, slash commands, host catalogs, delivery, scheduling,
and the packaging gates. It is the first verification step for every change, but it is not the
only one — the deployed copy is what users run.

## Commands

```bash
.venv/bin/pytest                       # full suite
.venv/bin/pytest tests/test_runner.py  # one file
```

Route tests import fastapi/httpx. Without them they **skip silently**, which is easy to mistake
for a pass. Run them for real with:

```bash
uv run --isolated --no-project --with pytest --with fastapi --with httpx pytest tests/test_dashboard.py
```

CI always provisions fastapi and httpx, so a route regression fails there even if it skips
locally.

## What each file pins

| File | Covers |
| --- | --- |
| `test_schema.py` | kinds, required fields, ids, edges, cycles, limits, condition grammar |
| `test_store.py` | name/run-id rules, atomic writes, missing vs corrupt, `recent` ordering |
| `test_convert.py` | plan mapping, stable ordering, note/trigger drops, dangling parents, cycles |
| `test_runner.py` | step semantics, pauses, resume validation, retries, rate-limit backoff, timeouts, retry reclaim, delivery receipts |
| `test_spawn.py` | facade injection, failure diagnosis, trust-gate messages |
| `test_profiles.py` / `test_models.py` | host catalog parsing, copy semantics, provider inference, degradation |
| `test_delivery.py` | rendering, truncation, send receipts, never raising |
| `test_channels.py` | directory parsing, non-messaging platforms, home-channel gate |
| `test_schedule.py` | cron building/validation/description, job naming, create vs update |
| `test_triggers.py` | replay prompt shape and name escaping |
| `test_commands.py` | `/workflow` grammar and result rendering |
| `test_register.py` | five tool registrations, JSON adapter, manifest agreement |
| `test_dashboard.py` | every route, expected-outcome statuses, profile-scoped home, resume/retry |
| `test_canvas_contract.py` | payloads shaped exactly as each GUI builds them |
| `test_canvas_ui.py` | cron and edge-key helper parity across the three canvas copies |
| `test_widget.py` | the widget stays dependency-free and self-contained |
| `test_tooltips.py` | every tooltip key exists in every canvas copy |
| `test_desktop.py` | Desktop contributions, `ctx.rest` usage, no direct fetch |
| `test_node_spec.py` | `node-spec.json` agrees with the schema and all canvases |

## Test seams

The suite never calls a real model, sends a real message, or touches a real scheduler:

- stores are constructed with an explicit `root=`;
- `llm_spawn(llm=fake)` injects a facade;
- delivery tests inject or monkeypatch the send seam;
- the scheduler tests monkeypatch `_cron`;
- route tests mount the router with an isolated `HERMES_HOME`.

A test that needs the host package should skip, not fail, when the host is absent — the package is
designed to import without it.

## What the suite cannot prove

- that the deployed copy was synced;
- that the host rebuilt it;
- that the Desktop app's separate `desktop/plugin.js` copy is current;
- that a real model call still works with the current provider credentials;
- that a real message actually arrived.

Those are the jobs of the live probes and the deployed-copy checks in
[Build and Packaging](repo-operations/build-and-packaging.md).

## Host gates

Two commands are part of verification, not optional polish:

```bash
hermes plugins validate .   # manifest vs registrations, security scan, desktop surface
hermes plugins doctor .     # discovery, parsing, import, registration, tool count
```

`doctor` also warns when the Desktop app is running a stale copy of `desktop/plugin.js`; that
warning is a real deployment problem, not noise.

## Related documentation

- [Repo Operations](repo-operations.md)
- [Live Probes](repo-operations/live-probes.md)
- [Build and Packaging](repo-operations/build-and-packaging.md)
