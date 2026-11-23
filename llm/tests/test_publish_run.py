"""publish_run.py's own logic: finding a run's files, and what it sends to MLflow - without
actually needing a server for the parts that don't need one."""

import json

import pytest

from drugwatch_llm.publish_run import load_run


def test_a_missing_run_info_is_a_clear_error_not_a_silent_skip(tmp_path, monkeypatch):
    import drugwatch_llm.publish_run as publish_run

    monkeypatch.setattr(publish_run, "RUN_DIR", tmp_path)
    (tmp_path / "some-run" / "adapter").mkdir(parents=True)
    # run_info.json deliberately not written

    with pytest.raises(FileNotFoundError, match="run_info.json"):
        load_run("some-run")


def test_a_missing_adapter_directory_is_a_clear_error(tmp_path, monkeypatch):
    import drugwatch_llm.publish_run as publish_run

    monkeypatch.setattr(publish_run, "RUN_DIR", tmp_path)
    run_dir = tmp_path / "some-run"
    run_dir.mkdir()
    (run_dir / "run_info.json").write_text(json.dumps({"model_id": "x"}))
    # adapter/ deliberately not created

    with pytest.raises(FileNotFoundError, match="adapter"):
        load_run("some-run")


def test_a_complete_run_loads_its_info_and_finds_its_adapter(tmp_path, monkeypatch):
    import drugwatch_llm.publish_run as publish_run

    monkeypatch.setattr(publish_run, "RUN_DIR", tmp_path)
    run_dir = tmp_path / "some-run"
    (run_dir / "adapter").mkdir(parents=True)
    info = {"model_id": "Qwen/Qwen2.5-1.5B-Instruct", "device": "cuda"}
    (run_dir / "run_info.json").write_text(json.dumps(info))

    loaded_info, adapter_dir = load_run("some-run")
    assert loaded_info == info
    assert adapter_dir == run_dir / "adapter"
