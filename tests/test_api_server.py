from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import zipfile

import httpx

from tests.helpers import write_minimal_settings


def request_json(app, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, json=json_body, params=params)

    return asyncio.run(send_request())


def request_raw(
    app,
    method: str,
    path: str,
    *,
    content: bytes,
    params: dict | None = None,
) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, content=content, params=params)

    return asyncio.run(send_request())


def test_get_config_returns_profiles_and_backends(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path, llm_overrides={"backends": ["codex_api"]})
    response = request_json(create_app(project_root=tmp_path), "GET", "/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "profiles": ["local_cpu"],
        "backends": ["codex_api", "agy", "codex_cli", "both"],
        "configured_backends": ["codex_api"],
        "default_backend": "codex_api",
        "default_ocr_backend": "codex_api",
        "active_profile": "local_cpu",
        "video_extensions": [".mkv", ".mov", ".mp4", ".webm"],
        "reference_extensions": [".txt", ".md", ".pdf"],
        "default_output_dir": str(tmp_path / "data/output/final"),
        "upload_dir": str(tmp_path / "data/uploads"),
        "content_types": ["book_club", "conversation"],
    }


def test_get_refine_default_instruction_returns_configured_prompt(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    response = request_json(create_app(project_root=tmp_path), "GET", "/api/refine-default-instruction")

    assert response.status_code == 200
    assert response.json()["prompt"] == "# test final cleanup"


def test_get_refine_default_instruction_returns_conversation_prompt(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    response = request_json(
        create_app(project_root=tmp_path),
        "GET",
        "/api/refine-default-instruction",
        params={"content_type": "conversation"},
    )

    assert response.status_code == 200
    assert response.json()["prompt"] == "# test conversation cleanup"


def test_frontend_settings_roundtrip_keeps_api_key_masked(tmp_path: Path, monkeypatch) -> None:
    from api_server import create_app

    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)
    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path)

    save_response = request_json(
        app,
        "PUT",
        "/api/frontend-settings",
        json_body={
            "codex_lb_base_url": "https://api.example.test",
            "codex_lb_api_key": "sk-test-secret",
            "profile": "local_cpu",
            "backend": "agy",
            "remote_concurrency": 4,
            "book_name": "测试书",
            "chapter": "第一章",
            "glossary_file": str(tmp_path / "glossary.txt"),
            "model": "gpt-5.5",
            "reasoning_effort": "high",
            "ocr_backend": "codex_api",
            "ocr_model": "gpt-5.4-mini",
            "ocr_reasoning_effort": "high",
        },
    )

    assert save_response.status_code == 200
    payload = save_response.json()
    assert payload["codex_lb_base_url"] == "https://api.example.test"
    assert payload["codex_lb_api_key"] == ""
    assert payload["has_codex_lb_api_key"] is True
    assert payload["profile"] == "local_cpu"
    assert payload["backend"] == "agy"
    assert payload["remote_concurrency"] == 4
    assert payload["book_name"] == "测试书"
    assert payload["chapter"] == "第一章"
    assert payload["glossary_file"].endswith("glossary.txt")
    assert payload["model"] == "gpt-5.5"
    assert payload["ocr_backend"] == "codex_api"
    assert payload["ocr_model"] == "gpt-5.4-mini"

    settings_path = tmp_path / "data/jobs/frontend-settings.json"
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert persisted["codex_lb_api_key"] == "sk-test-secret"
    assert persisted["backend"] == "agy"
    assert persisted["remote_concurrency"] == 4

    clear_response = request_json(
        app,
        "PUT",
        "/api/frontend-settings",
        json_body={"clear_codex_lb_api_key": True},
    )

    assert clear_response.status_code == 200
    assert clear_response.json()["has_codex_lb_api_key"] is False


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
    app = create_app(project_root=tmp_path)
    app.state.active_jobs.add("job-test-001")
    response = request_json(app, "GET", "/api/jobs/job-test-001")

    assert response.status_code == 200
    assert response.json()["id"] == "job-test-001"
    assert response.json()["status"] == "running"
    assert response.json()["current_stage"] == "transcribe"


def test_get_job_artifacts_lists_and_reads_text_outputs(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    (job_dir / "intermediate/asr").mkdir(parents=True, exist_ok=True)
    (job_dir / "intermediate/aligned").mkdir(parents=True, exist_ok=True)
    (job_dir / "intermediate/classified").mkdir(parents=True, exist_ok=True)
    (job_dir / "intermediate/refined").mkdir(parents=True, exist_ok=True)
    (job_dir / "output/final").mkdir(parents=True, exist_ok=True)
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(job_dir / "output/final/source.md"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_dir / "intermediate/asr/source.txt").write_text("原始转写文本", encoding="utf-8")
    (job_dir / "intermediate/aligned/source.json").write_text("{}", encoding="utf-8")
    (job_dir / "intermediate/classified/source.json").write_text("{}", encoding="utf-8")
    (job_dir / "intermediate/refined/source.json").write_text(
        json.dumps({"final_markdown": "# 校对结果\n\n正文", "refined_full_text": "校对结果 正文"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (job_dir / "output/final/source.md").write_text("# 最终稿\n\n正文", encoding="utf-8")

    app = create_app(project_root=tmp_path)
    list_response = request_json(app, "GET", "/api/jobs/job-test-001/artifacts")

    assert list_response.status_code == 200
    items = list_response.json()["items"]
    item_ids = {item["id"] for item in items}
    assert any(item["id"] == "transcribe-text" and item["exists"] for item in items)
    assert any(item["id"] == "refine-markdown" and item["exists"] for item in items)
    assert "align-json" not in item_ids
    assert "classify-json" not in item_ids

    content_response = request_json(app, "GET", "/api/jobs/job-test-001/artifacts/refine-markdown")

    assert content_response.status_code == 200
    assert content_response.json()["content"] == "# 校对结果\n\n正文"


def test_get_job_artifact_rejects_unknown_artifact_id(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs/job-test-001/artifacts/unknown-artifact")

    assert response.status_code == 404


def test_download_job_result_returns_generated_markdown(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    result_path = tmp_path / "data/output/final/lesson.md"
    job_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 最终稿\n\n正文", encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(result_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs/job-test-001/result")

    assert response.status_code == 200
    assert response.content == "# 最终稿\n\n正文".encode("utf-8")
    assert "attachment" in response.headers["content-disposition"]
    assert "lesson.md" in response.headers["content-disposition"]


def test_download_job_result_returns_generated_txt_from_markdown(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    result_path = tmp_path / "data/output/final/lesson.md"
    job_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 最终稿\n\n正文", encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(result_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs/job-test-001/result?format=txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.content == "最终稿\n\n正文\n".encode("utf-8")
    assert "lesson.txt" in response.headers["content-disposition"]


def test_download_job_result_rejects_unknown_format(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    result_path = tmp_path / "data/output/final/lesson.md"
    job_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 最终稿\n", encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(result_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs/job-test-001/result?format=pdf")

    assert response.status_code == 400


def test_download_job_result_rejects_unfinished_job(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "running",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "refine",
                "error_message": "",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app = create_app(project_root=tmp_path)
    app.state.active_jobs.add("job-test-001")

    response = request_json(app, "GET", "/api/jobs/job-test-001/result")

    assert response.status_code == 400


def test_download_job_result_falls_back_to_job_internal_final_output(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    internal_result_path = job_dir / "output/final/source.md"
    internal_result_path.parent.mkdir(parents=True, exist_ok=True)
    internal_result_path.write_text("# 内部保留结果\n", encoding="utf-8")
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:31:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(tmp_path / "missing/final.md"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/jobs/job-test-001/result")

    assert response.status_code == 200
    assert response.content == "# 内部保留结果\n".encode("utf-8")


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
    (job_a / "manifest.json").write_text(
        json.dumps(
            {
                "video_source": str(tmp_path / "videos/lesson-a.mp4"),
                "reference_source": str(tmp_path / "references/chapter-a.pdf"),
                "output_dir": str(tmp_path / "deliverables"),
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

    app = create_app(project_root=tmp_path)
    app.state.active_jobs.add("job-b")
    response = request_json(app, "GET", "/api/jobs")

    assert response.status_code == 200
    payload = response.json()["items"]
    assert [item["id"] for item in payload] == ["job-b", "job-a"]
    assert payload[1]["input_summary"] == {
        "video_source": str(tmp_path / "videos/lesson-a.mp4"),
        "reference_source": str(tmp_path / "references/chapter-a.pdf"),
        "output_dir": str(tmp_path / "deliverables"),
    }


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

    app = create_app(project_root=tmp_path)
    app.state.active_jobs.add("batch-test-001")
    response = request_json(app, "GET", "/api/batches/batch-test-001")

    assert response.status_code == 200
    assert response.json()["id"] == "batch-test-001"
    assert response.json()["items"][0]["job_id"] == "job-1"


def test_get_batches_lists_persisted_batch_states(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_dir = tmp_path / "data/jobs/batches/batch-test-001"
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "batch-test-001",
                "kind": "batch",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": "/tmp/summary.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/batches")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "batch-test-001"


def test_download_batch_item_result_returns_child_markdown(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_dir = tmp_path / "data/jobs/batches/batch-test-001"
    result_path = tmp_path / "data/output/final/lesson-a.md"
    batch_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 子任务结果\n", encoding="utf-8")
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "batch-test-001",
                "kind": "batch",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(batch_dir / "summary.json"),
                "items": [
                    {
                        "job_id": "job-a",
                        "status": "success",
                        "copied_output_path": str(result_path),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/batches/batch-test-001/items/job-a/result")

    assert response.status_code == 200
    assert response.content == "# 子任务结果\n".encode("utf-8")
    assert "lesson-a.md" in response.headers["content-disposition"]


def test_download_batch_item_result_returns_child_txt(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_dir = tmp_path / "data/jobs/batches/batch-test-001"
    result_path = tmp_path / "data/output/final/lesson-a.md"
    batch_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 子任务结果\n", encoding="utf-8")
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "batch-test-001",
                "kind": "batch",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(batch_dir / "summary.json"),
                "items": [
                    {
                        "job_id": "job-a",
                        "status": "success",
                        "copied_output_path": str(result_path),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/batches/batch-test-001/items/job-a/result?format=txt")

    assert response.status_code == 200
    assert response.content == "子任务结果\n".encode("utf-8")
    assert "lesson-a.txt" in response.headers["content-disposition"]


def test_download_batch_result_packs_summary_and_successful_outputs(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_dir = tmp_path / "data/jobs/batches/batch-test-001"
    result_path = tmp_path / "data/output/final/lesson-a.md"
    batch_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 子任务结果\n", encoding="utf-8")
    (batch_dir / "summary.md").write_text("# Batch Summary\n", encoding="utf-8")
    (batch_dir / "summary.json").write_text('{"total": 1}', encoding="utf-8")
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "batch-test-001",
                "kind": "batch",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(batch_dir / "summary.json"),
                "items": [
                    {
                        "job_id": "job-a",
                        "status": "success",
                        "copied_output_path": str(result_path),
                    },
                    {
                        "job_id": "job-b",
                        "status": "failed",
                        "copied_output_path": "",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/batches/batch-test-001/result")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "summary.md" in names
        assert "summary.json" in names
        assert "results/001-job-a-lesson-a.md" in names
        assert archive.read("results/001-job-a-lesson-a.md").decode("utf-8") == "# 子任务结果\n"


def test_download_batch_result_packs_txt_outputs(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_dir = tmp_path / "data/jobs/batches/batch-test-001"
    result_path = tmp_path / "data/output/final/lesson-a.md"
    batch_dir.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("# 子任务结果\n", encoding="utf-8")
    (batch_dir / "summary.md").write_text("# Batch Summary\n", encoding="utf-8")
    (batch_dir / "summary.json").write_text('{"total": 1}', encoding="utf-8")
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "batch-test-001",
                "kind": "batch",
                "status": "success",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(batch_dir / "summary.json"),
                "items": [
                    {
                        "job_id": "job-a",
                        "status": "success",
                        "copied_output_path": str(result_path),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/batches/batch-test-001/result?format=txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "batch-test-001-results-txt.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "summary.md" in names
        assert "summary.json" in names
        assert "results/001-job-a-lesson-a.txt" in names
        assert archive.read("results/001-job-a-lesson-a.txt").decode("utf-8") == "子任务结果\n"


def test_get_stage_runs_lists_persisted_stage_states(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    run_dir = tmp_path / "data/jobs/stage-runs/run-test-001"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "run-test-001",
                "kind": "stage-run",
                "status": "failed",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "refine",
                "error_message": "测试失败",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", "/api/stage-runs")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "run-test-001"


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


def test_post_upload_writes_video_under_project_upload_dir(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path)

    response = request_raw(
        app,
        "POST",
        "/api/uploads",
        params={"kind": "video", "filename": "../课程:1.MP4"},
        content=b"video-bytes",
    )

    assert response.status_code == 200
    payload = response.json()
    uploaded_path = Path(payload["path"])
    assert payload["kind"] == "video"
    assert payload["name"] == "课程_1.mp4"
    assert payload["size"] == len(b"video-bytes")
    assert payload["directory"] == str(uploaded_path.parent)
    assert uploaded_path.read_bytes() == b"video-bytes"
    assert uploaded_path.is_relative_to(tmp_path / "data/uploads/videos")


def test_post_upload_groups_directory_files(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path)

    first_response = request_raw(
        app,
        "POST",
        "/api/uploads",
        params={
            "kind": "reference",
            "filename": "chapter-01.txt",
            "group_id": "group-001",
            "relative_path": "references/chapter-01.txt",
        },
        content=b"chapter 1",
    )
    second_response = request_raw(
        app,
        "POST",
        "/api/uploads",
        params={
            "kind": "reference",
            "filename": "chapter-02.md",
            "group_id": "group-001",
            "relative_path": "references/chapter-02.md",
        },
        content=b"chapter 2",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_payload = first_response.json()
    second_payload = second_response.json()
    assert first_payload["directory"] == second_payload["directory"]
    uploaded_dir = Path(first_payload["directory"])
    assert uploaded_dir.is_relative_to(tmp_path / "data/uploads/reference")
    assert (uploaded_dir / "chapter-01.txt").read_bytes() == b"chapter 1"
    assert (uploaded_dir / "chapter-02.md").read_bytes() == b"chapter 2"


def test_post_upload_rejects_unsupported_extension(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path)

    response = request_raw(
        app,
        "POST",
        "/api/uploads",
        params={"kind": "video", "filename": "lesson.txt"},
        content=b"not-video",
    )

    assert response.status_code == 400
    assert "不支持的上传文件类型" in response.text


def test_post_upload_rejects_empty_file(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path)

    response = request_raw(
        app,
        "POST",
        "/api/uploads",
        params={"kind": "reference", "filename": "chapter.txt"},
        content=b"",
    )

    assert response.status_code == 400
    assert "上传文件为空" in response.text


def test_post_stage_input_writes_file_under_stage_input_upload_root(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    response = request_raw(
        create_app(project_root=tmp_path),
        "POST",
        "/api/stage-inputs/transcribe/audio",
        content=b"audio-bytes",
        params={"filename": "lesson.wav"},
    )

    assert response.status_code == 200
    uploaded_path = Path(response.json()["path"])
    assert uploaded_path.is_relative_to(tmp_path / "data/uploads/stage-inputs/transcribe/audio")
    assert uploaded_path.read_bytes() == b"audio-bytes"


def test_post_stage_input_rejects_file_extension_outside_slot_contract(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    response = request_raw(
        create_app(project_root=tmp_path),
        "POST",
        "/api/stage-inputs/transcribe/audio",
        content=b"not-audio",
        params={"filename": "lesson.txt"},
    )

    assert response.status_code == 400
    assert "音频文件不支持 .txt" in response.text


def test_post_stage_file_run_rejects_path_outside_stage_input_upload_root(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    outside_path = tmp_path / "lesson.wav"
    outside_path.write_bytes(b"audio")

    response = request_json(
        create_app(project_root=tmp_path),
        "POST",
        "/api/stages/transcribe/file-run",
        json_body={
            "input_files": {"audio": str(outside_path)},
            "result_name": "lesson-asr",
        },
    )

    assert response.status_code == 400
    assert "暂存文件" in response.text


def test_stage_file_run_uses_isolated_workspace_and_downloads_result(tmp_path: Path, monkeypatch) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)

    def fake_run_stage(stage_name, loaded_settings, logger, backend_override=None) -> int:
        _ = logger, backend_override
        assert stage_name == "transcribe"
        assert (loaded_settings.path_for("audio_dir") / "source.wav").read_bytes() == b"audio-bytes"
        output_path = loaded_settings.path_for("asr_dir") / "source.txt"
        output_path.write_text("转录结果", encoding="utf-8")
        return 0

    monkeypatch.setattr("src.web.tasks.run_stage", fake_run_stage)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)
    upload_response = request_raw(
        app,
        "POST",
        "/api/stage-inputs/transcribe/audio",
        content=b"audio-bytes",
        params={"filename": "lesson.wav"},
    )
    assert upload_response.status_code == 200

    submit_response = request_json(
        app,
        "POST",
        "/api/stages/transcribe/file-run",
        json_body={
            "input_files": {"audio": upload_response.json()["path"]},
            "result_name": "lesson-asr",
            "profile": "local_cpu",
        },
    )

    assert submit_response.status_code == 202
    run_id = submit_response.json()["run_id"]
    state = request_json(app, "GET", f"/api/stage-runs/{run_id}").json()
    assert state["status"] == "success"
    assert state["run_mode"] == "file"
    assert state["download_name"] == "lesson-asr.zip"
    assert not (tmp_path / "data/input/audio/source.wav").exists()

    result_response = request_json(app, "GET", f"/api/stage-runs/{run_id}/result")
    assert result_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result_response.content)) as archive:
        assert archive.namelist() == ["asr/source.txt"]
        assert archive.read("asr/source.txt").decode("utf-8") == "转录结果"


def test_stage_file_run_executes_export_with_uploaded_refinement_json(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)
    upload_response = request_raw(
        app,
        "POST",
        "/api/stage-inputs/export-markdown/refined_json",
        content=json.dumps({"final_markdown": "# 整理稿\n\n正文"}, ensure_ascii=False).encode("utf-8"),
        params={"filename": "refined-result.json"},
    )
    assert upload_response.status_code == 200

    submit_response = request_json(
        app,
        "POST",
        "/api/stages/export-markdown/file-run",
        json_body={
            "input_files": {"refined_json": upload_response.json()["path"]},
            "result_name": "exported-draft",
        },
    )

    assert submit_response.status_code == 202
    run_id = submit_response.json()["run_id"]
    state = request_json(app, "GET", f"/api/stage-runs/{run_id}").json()
    assert state["status"] == "success"
    assert not (tmp_path / "data/intermediate/refined/source.json").exists()

    result_response = request_json(app, "GET", f"/api/stage-runs/{run_id}/result")
    assert result_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result_response.content)) as archive:
        assert archive.read("final/source.md").decode("utf-8") == "# 整理稿\n\n正文\n"
        assert "final/source.txt" in archive.namelist()


def test_stage_file_result_download_rejects_archive_outside_its_run_directory(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    run_id = "stage-file-outside"
    state_path = tmp_path / "data/jobs/stage-runs" / run_id / "state.json"
    outside_archive = tmp_path / "outside.zip"
    outside_archive.write_bytes(b"not-a-real-archive")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "id": run_id,
                "kind": "stage-run",
                "status": "success",
                "run_mode": "file",
                "output_path": str(outside_archive),
                "download_name": "outside.zip",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = request_json(create_app(project_root=tmp_path), "GET", f"/api/stage-runs/{run_id}/result")

    assert response.status_code == 500
    assert "结果路径无效" in response.text


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
    assert state["input_summary"] == {
        "content_type": "book_club",
        "video_source": str(tmp_path / "lesson.mp4"),
        "reference_source": str(tmp_path / "chapter.txt"),
        "output_dir": str(tmp_path / "deliverables"),
    }


def test_post_conversation_job_allows_missing_reference(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    def fake_execute_single_job(*, app, job_id: str, payload: dict) -> None:
        assert payload["content_type"] == "conversation"
        assert payload.get("reference") is None
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
            "video": str(tmp_path / "conversation.mp4"),
            "output_dir": str(tmp_path / "deliverables"),
            "content_type": "conversation",
        },
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    state = json.loads((tmp_path / "data/jobs" / job_id / "state.json").read_text(encoding="utf-8"))
    assert state["input_summary"] == {
        "content_type": "conversation",
        "video_source": str(tmp_path / "conversation.mp4"),
        "output_dir": str(tmp_path / "deliverables"),
    }


def test_post_job_applies_saved_frontend_model_settings(tmp_path: Path, monkeypatch) -> None:
    from api_server import create_app
    from src.refine_utils import load_markdown_assemble_prompt

    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)
    write_minimal_settings(tmp_path)
    video_path = tmp_path / "lesson.mp4"
    reference_path = tmp_path / "chapter.txt"
    output_dir = tmp_path / "deliverables"
    video_path.write_bytes(b"video")
    reference_path.write_text("参考", encoding="utf-8")
    seen: dict[str, str] = {}

    def fake_run_stage(stage_name, job_loaded_settings, logger, backend_override=None) -> int:
        _ = logger
        if stage_name == "refine":
            seen["backend_override"] = backend_override or ""
            seen["model"] = job_loaded_settings.settings.llm.model
            seen["reasoning_effort"] = job_loaded_settings.settings.llm.reasoning_effort
            seen["ocr_backend"] = job_loaded_settings.settings.reference.ai_ocr_backend
            seen["ocr_model"] = job_loaded_settings.settings.reference.codex_ocr_model
            seen["ocr_reasoning_effort"] = job_loaded_settings.settings.reference.codex_ocr_reasoning_effort
            seen["refine_prompt"] = load_markdown_assemble_prompt(job_loaded_settings)
        if stage_name == "export-markdown":
            final_dir = job_loaded_settings.path_for("final_dir")
            final_dir.mkdir(parents=True, exist_ok=True)
            (final_dir / "source.md").write_text("# 结果\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("src.web.tasks.run_stage", fake_run_stage)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    request_json(
        app,
        "PUT",
        "/api/frontend-settings",
        json_body={
            "model": "gpt-5.5",
            "reasoning_effort": "high",
            "backend": "agy",
            "ocr_backend": "agy",
            "ocr_model": "gpt-5.4-mini",
            "ocr_reasoning_effort": "high",
        },
    )
    response = request_json(
        app,
        "POST",
        "/api/jobs",
        json_body={
            "video": str(video_path),
            "reference": str(reference_path),
            "output_dir": str(output_dir),
            "refine_prompt": "# 单任务自定义阶段六指令\n\n请保留讲解原话。",
        },
    )

    assert response.status_code == 202
    assert seen == {
        "backend_override": "agy",
        "model": "gpt-5.5",
        "reasoning_effort": "high",
        "ocr_backend": "agy",
        "ocr_model": "gpt-5.4-mini",
        "ocr_reasoning_effort": "high",
        "refine_prompt": "# 单任务自定义阶段六指令\n\n请保留讲解原话。",
    }


def test_post_job_rerun_returns_job_id_and_updates_existing_state(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "failed",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "refine",
                "error_message": "旧错误",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    def fake_execute_job_rerun(*, app, job_id: str, payload: dict) -> None:
        assert payload["start_stage"] == "refine"
        app.state.update_state(
            app.state.job_state_path(job_id),
            status="success",
            current_stage="done",
            error_message="",
            output_path=str(tmp_path / "deliverables/final.md"),
        )
        app.state.active_jobs.discard(job_id)

    app.state.execute_job_rerun = fake_execute_job_rerun

    response = request_json(
        app,
        "POST",
        "/api/jobs/job-test-001/rerun",
        json_body={"start_stage": "refine"},
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-test-001"
    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["current_stage"] == "done"
    assert state["error_message"] == ""


def test_post_job_rerun_rejects_active_job(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    job_dir = tmp_path / "data/jobs/job-test-001"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "job-test-001",
                "kind": "job",
                "status": "running",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "transcribe",
                "error_message": "",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app = create_app(project_root=tmp_path, run_tasks_inline=True)
    app.state.active_jobs.add("job-test-001")

    response = request_json(
        app,
        "POST",
        "/api/jobs/job-test-001/rerun",
        json_body={"start_stage": "refine"},
    )

    assert response.status_code == 400
    assert "不能重跑正在运行的任务" in response.text


def test_resolve_rerun_stages_returns_selected_suffix() -> None:
    from src.web.tasks import resolve_rerun_stages

    assert resolve_rerun_stages(
        ["extract_audio", "transcribe", "prepare_reference", "refine", "export_markdown"],
        "prepare-reference",
    ) == ["prepare-reference", "refine", "export-markdown"]


def test_post_job_rerun_executes_selected_stage_suffix(tmp_path: Path, monkeypatch) -> None:
    from api_server import create_app
    from src.config_loader import load_settings
    from src.job_runner import build_job_paths, write_job_settings

    write_minimal_settings(tmp_path)
    base_loaded_settings = load_settings(project_root=tmp_path)
    job_id = "job-test-001"
    job_paths = build_job_paths(tmp_path, job_id)
    write_job_settings(
        project_root=tmp_path,
        loaded_settings=base_loaded_settings,
        job_paths=job_paths,
        profile_name="local_cpu",
    )
    (job_paths.manifest_path).write_text(
        json.dumps(
            {
                "job_id": job_id,
                "profile": "local_cpu",
                "video_source": str(tmp_path / "lesson.mp4"),
                "reference_source": str(tmp_path / "reference.txt"),
                "output_dir": str(tmp_path / "deliverables"),
                "book_name": "",
                "chapter": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_paths.job_root / "state.json").write_text(
        json.dumps(
            {
                "id": job_id,
                "kind": "job",
                "status": "failed",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "refine",
                "error_message": "旧错误",
                "output_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    called_stages: list[str] = []

    def fake_run_stage(stage_name, job_loaded_settings, logger, backend_override=None) -> int:
        _ = logger, backend_override
        called_stages.append(stage_name)
        if stage_name == "export-markdown":
            final_dir = job_loaded_settings.path_for("final_dir")
            final_dir.mkdir(parents=True, exist_ok=True)
            (final_dir / "source.md").write_text("# 重跑结果\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("src.web.tasks.run_stage", fake_run_stage)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    response = request_json(
        app,
        "POST",
        f"/api/jobs/{job_id}/rerun",
        json_body={"start_stage": "prepare-reference"},
    )

    assert response.status_code == 202
    assert called_stages == ["prepare-reference", "refine", "export-markdown"]
    state = json.loads((job_paths.job_root / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["current_stage"] == "done"
    assert state["error_message"] == ""
    assert state["output_path"].endswith("lesson.md")
    assert Path(state["output_path"]).exists()


def test_post_batch_item_rerun_executes_suffix_and_updates_batch_state(tmp_path: Path, monkeypatch) -> None:
    from api_server import create_app
    from src.config_loader import load_settings
    from src.job_runner import build_batch_root, build_job_paths, write_job_settings

    write_minimal_settings(tmp_path)
    base_loaded_settings = load_settings(project_root=tmp_path)
    batch_id = "batch-test-001"
    job_id = "job-test-001"
    job_paths = build_job_paths(tmp_path, job_id)
    write_job_settings(
        project_root=tmp_path,
        loaded_settings=base_loaded_settings,
        job_paths=job_paths,
        profile_name="local_cpu",
    )
    (job_paths.manifest_path).write_text(
        json.dumps(
            {
                "job_id": job_id,
                "profile": "local_cpu",
                "video_source": str(tmp_path / "lesson.mp4"),
                "reference_source": str(tmp_path / "reference.txt"),
                "output_dir": str(tmp_path / "deliverables"),
                "book_name": "",
                "chapter": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    batch_root = build_batch_root(tmp_path, batch_id)
    batch_root.mkdir(parents=True, exist_ok=True)
    (batch_root / "state.json").write_text(
        json.dumps(
            {
                "id": batch_id,
                "kind": "batch",
                "status": "failed",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": str(batch_root / "summary.json"),
                "total": 1,
                "success": 0,
                "failed": 1,
                "items": [
                    {
                        "job_id": job_id,
                        "mode": "paired-dir",
                        "video_source": str(tmp_path / "lesson.mp4"),
                        "reference_source": str(tmp_path / "reference.txt"),
                        "output_dir": str(tmp_path / "deliverables"),
                        "book_name": "",
                        "chapter": "",
                        "glossary_file": "",
                        "status": "failed",
                        "failed_stage": "refine",
                        "error_message": "旧错误",
                        "copied_output_path": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    called_stages: list[str] = []

    def fake_run_stage(stage_name, job_loaded_settings, logger, backend_override=None) -> int:
        _ = logger, backend_override
        called_stages.append(stage_name)
        if stage_name == "export-markdown":
            final_dir = job_loaded_settings.path_for("final_dir")
            final_dir.mkdir(parents=True, exist_ok=True)
            (final_dir / "source.md").write_text("# 批量子任务重跑结果\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("src.web.tasks.run_stage", fake_run_stage)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    response = request_json(
        app,
        "POST",
        f"/api/batches/{batch_id}/items/{job_id}/rerun",
        json_body={"start_stage": "refine"},
    )

    assert response.status_code == 202
    assert response.json() == {"batch_id": batch_id, "job_id": job_id}
    assert called_stages == ["refine", "export-markdown"]
    state = json.loads((batch_root / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["success"] == 1
    assert state["failed"] == 0
    assert state["items"][0]["status"] == "success"
    assert state["items"][0]["failed_stage"] == ""
    assert state["items"][0]["copied_output_path"].endswith("lesson.md")
    assert Path(state["items"][0]["copied_output_path"]).exists()
    summary = json.loads((batch_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["success"] == 1
    assert summary["items"][0]["status"] == "success"
    assert (batch_root / "item-reruns" / job_id / "state.json").exists()
    assert not (job_paths.job_root / "state.json").exists()


def test_post_batch_item_rerun_rejects_active_or_non_terminal_item(tmp_path: Path) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    batch_id = "batch-test-001"
    batch_dir = tmp_path / "data/jobs/batches" / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "state.json").write_text(
        json.dumps(
            {
                "id": batch_id,
                "kind": "batch",
                "status": "failed",
                "created_at": "2026-03-16T01:30:00+08:00",
                "updated_at": "2026-03-16T01:40:00+08:00",
                "current_stage": "done",
                "error_message": "",
                "output_path": "",
                "items": [{"job_id": "job-a", "status": "pending"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    response = request_json(
        app,
        "POST",
        f"/api/batches/{batch_id}/items/job-a/rerun",
        json_body={"start_stage": "refine"},
    )

    assert response.status_code == 400
    assert "只能重跑已成功或已失败的批量子任务" in response.text

    app.state.active_jobs.add(batch_id)
    response = request_json(
        app,
        "POST",
        f"/api/batches/{batch_id}/items/job-a/rerun",
        json_body={"start_stage": "refine"},
    )

    assert response.status_code == 400
    assert "不能在批量任务运行中重跑子任务" in response.text


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
    assert state["input_summary"] == {"content_type": "book_club", "manifest": str(tmp_path / "jobs.yaml")}


def test_execute_batch_job_passes_custom_refine_prompt_to_prepared_jobs(tmp_path: Path, monkeypatch) -> None:
    from api_server import create_app

    write_minimal_settings(tmp_path)
    manifest_path = tmp_path / "jobs.yaml"
    manifest_path.write_text(json.dumps({"jobs": []}, ensure_ascii=False), encoding="utf-8")
    seen: dict[str, str | None] = {}

    def fake_prepare_batch_jobs(**kwargs):
        seen["refine_prompt"] = kwargs.get("refine_prompt")
        return []

    monkeypatch.setattr("src.web.tasks.prepare_batch_jobs", fake_prepare_batch_jobs)
    app = create_app(project_root=tmp_path, run_tasks_inline=True)

    response = request_json(
        app,
        "POST",
        "/api/batch-jobs",
        json_body={
            "manifest": str(manifest_path),
            "remote_concurrency": 2,
            "refine_prompt": "# 批量自定义阶段六指令\n\n所有子任务统一使用。",
        },
    )

    assert response.status_code == 202
    assert seen["refine_prompt"] == "# 批量自定义阶段六指令\n\n所有子任务统一使用。"


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
