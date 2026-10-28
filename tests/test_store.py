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
