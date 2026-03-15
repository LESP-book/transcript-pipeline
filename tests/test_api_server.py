from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from tests.helpers import write_minimal_settings


def request_json(app, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body, params=params)

    return asyncio.run(send_request())


def test_get_config_returns_profiles_and_backends(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path, llm_overrides={"backends": ["codex_cli"]})
    response = request_json(create_app(project_root=tmp_path), "GET", "/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "profiles": ["local_cpu"],
        "backends": ["codex_cli", "gemini_cli", "both"],
        "configured_backends": ["codex_cli"],
        "active_profile": "local_cpu",
    }


def test_get_job_status_returns_current_state(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    state_dir = tmp_path / "data/jobs/job-test-001"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "running",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "transcribe",
                "error_message": "",
                "output_path": "",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs/job-test-001")

    assert response.status_code == 200
    assert response.json()["id"] == "job-test-001"
    assert response.json()["status"] == "running"
    assert response.json()["current_stage"] == "transcribe"


def test_get_jobs_lists_persisted_states(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
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

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["job-b", "job-a"]


def test_get_batch_status_returns_persisted_state(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_dir = tmp_path / "data/jobs/batches/batch-test-001"
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "batch-test-001",
                "kind": "batch",
                "status": "running",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "transcribe",
                "error_message": "",
                "output_path": "",
                "items": [{"job_id": "job-1", "status": "running"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/batches/batch-test-001")

    assert response.status_code == 200
    assert response.json()["id"] == "batch-test-001"
    assert response.json()["items"][0]["job_id"] == "job-1"


def test_get_fs_list_filters_hidden_entries_and_rejects_outside_roots(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    browse_root = tmp_path / "workspace"
    browse_root.mkdir(parents=True, exist_ok=True)
    (browse_root / "visible.txt").write_text("ok", encoding="utf-8")
    (browse_root / ".hidden.txt").write_text("secret", encoding="utf-8")
    (browse_root / "folder").mkdir()

    app = create_app(project_root=tmp_path)
    response = request_json(app, "GET", "/api/fs/list", params={"path": str(browse_root), "type": "all"})

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["folder", "visible.txt"]

    denied = request_json(app, "GET", "/api/fs/list", params={"path": "/tmp", "type": "all"})
    assert denied.status_code == 403


def test_post_job_returns_job_id_and_persists_state(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    def fake_execute_single_job(*, app, job_id: str, payload: dict) -> None:
        _ = payload
        app.state.update_state(
            app.state.job_state_path(job_id),
            status="success",
            current_stage="done",
            output_path=str(tmp_path / "deliverables/final.md"),
        )

    app.state.execute_single_job = fake_execute_single_job

    response = request_json(
        app,
        "POST",
        "/api/jobs",
        json_body={
            "video": str(tmp_path / "lesson.mp4"),
            "reference": str(tmp_path / "chapter.txt"),
            "output_dir": str(tmp_path / "deliverables"),
        },
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    state = json.loads((tmp_path / "data/jobs" / job_id / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["output_path"].endswith("final.md")


def test_post_batch_jobs_returns_batch_id_and_persists_state(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    def fake_execute_batch_job(*, app, batch_id: str, payload: dict) -> None:
        _ = payload
        app.state.update_state(
            app.state.batch_state_path(batch_id),
            status="success",
            current_stage="done",
            items=[{"job_id": "job-a", "status": "success"}],
        )

    app.state.execute_batch_job = fake_execute_batch_job

    response = request_json(
        app,
        "POST",
        "/api/batch-jobs",
        json_body={
            "manifest": str(tmp_path / "jobs.yaml"),
            "remote_concurrency": 2,
        },
    )

    assert response.status_code == 202
    batch_id = response.json()["batch_id"]
    state = json.loads((tmp_path / "data/jobs/batches" / batch_id / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["items"][0]["job_id"] == "job-a"


def test_post_stage_run_returns_run_id(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    def fake_execute_stage_run(*, app, run_id: str, stage_name: str, payload: dict) -> None:
        _ = payload
        app.state.update_state(
            app.state.stage_run_state_path(run_id),
            status="success",
            current_stage=stage_name,
        )

    app.state.execute_stage_run = fake_execute_stage_run

    response = request_json(
        app,
        "POST",
        "/api/stages/refine",
        json_body={"profile": "local_cpu", "backend": "codex_cli"},
    )

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    state = json.loads((tmp_path / "data/jobs/stage-runs" / run_id / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["current_stage"] == "refine"
