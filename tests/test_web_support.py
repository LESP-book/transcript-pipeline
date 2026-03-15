from __future__ import annotations

import json
from pathlib import Path


def test_state_store_update_state_persists_changes(tmp_path: Path) -> None:
    from src.web.state_store import create_initial_state, read_json_file, update_state, write_json_file

    state_path = tmp_path / "data/jobs/job-test-001/state.json"
    write_json_file(state_path, create_initial_state("job-test-001", "job"))

    updated_state = update_state(
        state_path,
        status="running",
        current_stage="transcribe",
        output_path=str(tmp_path / "out.md"),
    )

    assert updated_state["id"] == "job-test-001"
    assert updated_state["status"] == "running"
    assert updated_state["current_stage"] == "transcribe"
    assert updated_state["output_path"].endswith("out.md")

    persisted_state = read_json_file(state_path)
    assert persisted_state["status"] == "running"
    assert persisted_state["current_stage"] == "transcribe"


def test_state_store_collect_state_items_sorts_latest_first(tmp_path: Path) -> None:
    from src.web.state_store import collect_state_items

    job_a = tmp_path / "data/jobs/job-a"
    job_b = tmp_path / "data/jobs/job-b"
    job_a.mkdir(parents=True, exist_ok=True)
    job_b.mkdir(parents=True, exist_ok=True)
    (job_a / "state.json").write_text(
        json.dumps(
            {
                "id": "job-a",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:00:00+08:00",
                "updated_at": "2026-03-16T01:10:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": "/tmp/a.md",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_b / "state.json").write_text(
        json.dumps(
            {
                "id": "job-b",
                "kind": "job",
                "status": "running",
                "created_at": "2026-03-16T02:00:00+08:00",
                "updated_at": "2026-03-16T02:05:00+08:00",
                "current_stage": "refine",
                "error_message": "",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items = collect_state_items(tmp_path / "data/jobs")

    assert [item["id"] for item in items] == ["job-b", "job-a"]


def test_fs_browser_resolve_path_blocks_outside_allowed_roots(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from src.web.fs_browser import resolve_allowed_browse_path

    browse_root = tmp_path / "workspace"
    browse_root.mkdir(parents=True, exist_ok=True)

    current_path, allow_roots = resolve_allowed_browse_path(tmp_path, str(browse_root))

    assert current_path == browse_root.resolve()
    assert tmp_path.resolve() in allow_roots

    try:
        resolve_allowed_browse_path(tmp_path, "/tmp")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected browse path outside allow roots to be rejected")
