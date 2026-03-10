from __future__ import annotations

from fastapi import HTTPException

from src.asr_utils import AsrBatchItem, AsrOutputPaths
from src.ffmpeg_utils import AudioExtractionResult
from src.local_helper_api import (
    LocalPairingClaimRequest,
    create_app,
)
from src.local_helper_protocol import CreateLocalJobRequest
from src.pipeline_jobs import LocalPreprocessResult
from src.local_helper_service import LocalHelperService


def build_app():
    service = LocalHelperService()
    return create_app(service)


def get_route_endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_health_endpoint_reports_unpaired_state() -> None:
    app = build_app()
    endpoint = get_route_endpoint(app, "/v1/health", "GET")

    payload = endpoint()

    assert payload["ok"] is True
    assert payload["paired"] is False


def test_runtime_endpoint_returns_helper_status() -> None:
    app = build_app()
    endpoint = get_route_endpoint(app, "/v1/runtime", "GET")

    payload = endpoint()

    assert payload["helper_version"]
    assert "gpu_available" in payload


def test_pairing_and_create_job_flow() -> None:
    app = build_app()
    claim_pairing = get_route_endpoint(app, "/v1/pairing/claim", "POST")
    create_job = get_route_endpoint(app, "/v1/jobs", "POST")
    get_job = get_route_endpoint(app, "/v1/jobs/{local_job_id}", "GET")

    pairing = claim_pairing(
        LocalPairingClaimRequest(
            session_id="session-1",
            worker_id="worker-1",
            local_session_secret="secret-1",
        )
    )
    assert pairing["paired"] is True

    created = create_job(
        CreateLocalJobRequest(
            quality_tier="high",
            video_handle="video-1",
            reference_mode="url",
            reference_value="https://example.com/book",
            local_session_secret="secret-1",
        )
    )
    assert created["accepted"] is True

    job = get_job(created["local_job_id"])
    assert job["quality_tier"] == "high"
    assert job["status"] == "accepted"


def test_create_job_rejects_invalid_secret() -> None:
    app = build_app()
    claim_pairing = get_route_endpoint(app, "/v1/pairing/claim", "POST")
    create_job = get_route_endpoint(app, "/v1/jobs", "POST")

    claim_pairing(
        LocalPairingClaimRequest(
            session_id="session-1",
            worker_id="worker-1",
            local_session_secret="secret-1",
        )
    )

    try:
        create_job(
            CreateLocalJobRequest(
                quality_tier="general",
                video_handle="video-1",
                reference_mode="local_file",
                reference_value="chapter.pdf",
                local_session_secret="wrong-secret",
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected HTTPException")


def test_process_job_endpoint_runs_local_pipeline_and_pushes_remote(tmp_path) -> None:
    service = LocalHelperService()

    class FakeRemoteGateway:
        def __init__(self) -> None:
            self.statuses: list[str] = []

        def create_job(self, **kwargs):
            _ = kwargs
            return "remote-1"

        def update_job_status(self, job_id: str, status: str) -> None:
            _ = job_id
            self.statuses.append(status)

        def attach_artifact(self, job_id: str, kind: str, storage_path: str, content_type: str) -> None:
            _ = job_id, kind, storage_path, content_type

    asr_json = tmp_path / "source.json"
    asr_txt = tmp_path / "source.txt"
    asr_json.write_text("{}", encoding="utf-8")
    asr_txt.write_text("正文", encoding="utf-8")
    preprocess_result = LocalPreprocessResult(
        quality_tier_name="general",
        extracted_audio=[
            AudioExtractionResult(
                video_path=tmp_path / "video.mp4",
                audio_path=tmp_path / "audio.wav",
                status="created",
            )
        ],
        transcribed_audio=[
            AsrBatchItem(
                source_audio_path=tmp_path / "audio.wav",
                output_paths=AsrOutputPaths(json_path=asr_json, txt_path=asr_txt),
                segment_count=1,
            )
        ],
    )
    app = create_app(
        service,
        remote_gateway=FakeRemoteGateway(),
        preprocess_executor=lambda quality_tier_name: preprocess_result,
    )
    claim_pairing = get_route_endpoint(app, "/v1/pairing/claim", "POST")
    create_job = get_route_endpoint(app, "/v1/jobs", "POST")
    process_job = get_route_endpoint(app, "/v1/jobs/{local_job_id}/process", "POST")
    get_job = get_route_endpoint(app, "/v1/jobs/{local_job_id}", "GET")

    claim_pairing(
        LocalPairingClaimRequest(
            session_id="session-1",
            worker_id="worker-1",
            local_session_secret="secret-1",
        )
    )
    created = create_job(
        CreateLocalJobRequest(
            quality_tier="general",
            video_handle="video-1",
            reference_mode="url",
            reference_value="https://example.com/book",
            local_session_secret="secret-1",
        )
    )

    processed = process_job(created["local_job_id"])
    job = get_job(created["local_job_id"])

    assert processed["status"] == "queued_server"
    assert job["status"] == "queued_server"
    assert job["remote_job_id"] == "remote-1"
