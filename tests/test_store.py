import json

import pytest

from visual_workflow_hermes.store import DesignStore


def _graph(name="t"):
    return {"name": name, "nodes": [
        {"id": "trigger1", "type": "trigger", "trigger_mode": "manual", "after": []},
        {"id": "a", "type": "agent", "prompt": "hi", "after": ["trigger1"]},
        {"id": "out", "type": "output", "after": ["a"]},
    ]}


def test_save_then_load_roundtrip(tmp_path):
    s = DesignStore(root=tmp_path)
    s.save("demo", _graph())
    assert s.load("demo")["name"] == "t"
    assert (tmp_path / "demo.json").exists()


def test_saved_file_is_pretty_printed_json(tmp_path):
    s = DesignStore(root=tmp_path)
    s.save("demo", _graph())
    text = (tmp_path / "demo.json").read_text()
    assert text.endswith("\n")
    assert json.loads(text)["nodes"][0]["type"] == "trigger"


def test_save_rejects_invalid_graph(tmp_path):
    s = DesignStore(root=tmp_path)
    with pytest.raises(ValueError):
        s.save("bad", {"name": "bad", "nodes": []})
    assert not (tmp_path / "bad.json").exists()


def test_rejects_bad_names(tmp_path):
    s = DesignStore(root=tmp_path)
    with pytest.raises(ValueError):
        s.save("../escape", _graph())
    with pytest.raises(FileNotFoundError):
        s.load("missing")


def test_list_designs_sorted(tmp_path):
    s = DesignStore(root=tmp_path)
    s.save("b-one", _graph("b"))
    s.save("a-one", _graph("a"))
    assert s.list_designs() == ["a-one", "b-one"]


def test_save_overwrites_same_name_only(tmp_path):
    s = DesignStore(root=tmp_path)
    s.save("demo", _graph("first"))
    s.save("demo", _graph("second"))
    assert s.load("demo")["name"] == "second"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["demo.json"]


def test_notes_keep_their_position_and_text_through_save_and_load(tmp_path):
    """A sticky note is canvas state: the store must not normalise it away."""
    s = DesignStore(root=tmp_path)
    graph = _graph()
    graph["nodes"].append({
        "id": "note1", "type": "note", "text": "keep the tone dry",
        "color": "blue", "x": 210, "y": 96,
    })
    s.save("demo", graph)
    note = next(n for n in s.load("demo")["nodes"] if n["type"] == "note")
    assert note == {"id": "note1", "type": "note", "text": "keep the tone dry",
                    "color": "blue", "x": 210, "y": 96}


# -- run history ------------------------------------------------------------
def test_run_store_recent_is_newest_first_and_limited(tmp_path):
    import os

    from visual_workflow_hermes.store import RunStore

    runs = RunStore(root=tmp_path)
    for index, run_id in enumerate(("aaaaaa01", "aaaaaa02", "aaaaaa03")):
        runs.save({"run_id": run_id, "name": "demo", "status": "done"})
        path = tmp_path / f"{run_id}.json"
        os.utime(path, (1_700_000_000 + index * 60, 1_700_000_000 + index * 60))

    assert [r["run_id"] for r in runs.recent()] == ["aaaaaa03", "aaaaaa02", "aaaaaa01"]
    assert [r["run_id"] for r in runs.recent(limit=1)] == ["aaaaaa03"]


def test_run_store_recent_skips_corrupt_and_foreign_files(tmp_path):
    from visual_workflow_hermes.store import RunStore

    runs = RunStore(root=tmp_path)
    runs.save({"run_id": "bbbbbb01", "name": "demo", "status": "awaiting_approval"})
    (tmp_path / "bbbbbb02.json").write_text("{not json")
    (tmp_path / "notes.json").write_text("{\"status\": \"done\"}")
    rows = runs.recent()
    assert [r["run_id"] for r in rows] == ["bbbbbb01"]
