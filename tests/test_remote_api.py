from __future__ import annotations

from fastapi import HTTPException

from src.remote_api import (
    AttachArtifactRequest,
    ClaimPairingRequest,
    CreateJobRequest,
    CreatePairingRequest,
    UpdateJobStatusRequest,
    create_app,
)
from src.remote_service import RemoteCoordinationService


def build_app():
    service = RemoteCoordinationService()
    return create_app(service)


def get_route_endpoint(app, path: str, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def test_create_anonymous_session_endpoint() -> None:
    app = build_app()
    endpoint = get_route_endpoint(app, "/api/anonymous-sessions", "POST")

    payload = endpoint()
    assert payload["session_id"]


def test_pairing_flow_endpoints() -> None:
    app = build_app()
    create_session = get_route_endpoint(app, "/api/anonymous-sessions", "POST")
    create_pairing = get_route_endpoint(app, "/api/pairings", "POST")
    claim_pairing = get_route_endpoint(app, "/api/helper/pairings/claim", "POST")

    session_id = create_session()["session_id"]
    code = create_pairing(CreatePairingRequest(session_id=session_id))["code"]
    claimed = claim_pairing(ClaimPairingRequest(code=code, worker_id="worker-1"))

    assert claimed["status"] == "claimed"
    assert claimed["worker_id"] == "worker-1"
    assert claimed["local_session_secret"]


def test_create_job_and_list_jobs_for_session() -> None:
    app = build_app()
    create_session = get_route_endpoint(app, "/api/anonymous-sessions", "POST")
    create_pairing = get_route_endpoint(app, "/api/pairings", "POST")
    claim_pairing = get_route_endpoint(app, "/api/helper/pairings/claim", "POST")
    create_job = get_route_endpoint(app, "/api/helper/jobs", "POST")
    list_jobs = get_route_endpoint(app, "/api/jobs", "GET")

    session_id = create_session()["session_id"]
    code = create_pairing(CreatePairingRequest(session_id=session_id))["code"]
    claim_pairing(ClaimPairingRequest(code=code, worker_id="worker-1"))

    job_id = create_job(
        CreateJobRequest(
            session_id=session_id,
            worker_id="worker-1",
            quality_tier="high",
            reference_mode="url",
            reference_value="https://example.com/book",
        )
    )["job_id"]

    jobs = list_jobs(x_session_id=session_id)["items"]
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == job_id


def test_get_job_for_wrong_session_returns_403() -> None:
    app = build_app()
    create_session = get_route_endpoint(app, "/api/anonymous-sessions", "POST")
    create_pairing = get_route_endpoint(app, "/api/pairings", "POST")
    claim_pairing = get_route_endpoint(app, "/api/helper/pairings/claim", "POST")
    create_job = get_route_endpoint(app, "/api/helper/jobs", "POST")
    get_job = get_route_endpoint(app, "/api/jobs/{job_id}", "GET")

    session_a = create_session()["session_id"]
    session_b = create_session()["session_id"]
    code = create_pairing(CreatePairingRequest(session_id=session_a))["code"]
    claim_pairing(ClaimPairingRequest(code=code, worker_id="worker-1"))
    job_id = create_job(
        CreateJobRequest(
            session_id=session_a,
            worker_id="worker-1",
            quality_tier="general",
            reference_mode="local_file",
            reference_value="chapter.pdf",
        )
    )["job_id"]

    try:
        get_job(job_id, x_session_id=session_b)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected HTTPException")


def test_helper_can_update_job_status_and_attach_artifact() -> None:
    app = build_app()
    create_session = get_route_endpoint(app, "/api/anonymous-sessions", "POST")
    create_pairing = get_route_endpoint(app, "/api/pairings", "POST")
    claim_pairing = get_route_endpoint(app, "/api/helper/pairings/claim", "POST")
    create_job = get_route_endpoint(app, "/api/helper/jobs", "POST")
    update_job_status = get_route_endpoint(app, "/api/helper/jobs/{job_id}/status", "POST")
    attach_artifact = get_route_endpoint(app, "/api/helper/jobs/{job_id}/artifacts", "POST")
    get_job = get_route_endpoint(app, "/api/jobs/{job_id}", "GET")

    session_id = create_session()["session_id"]
    code = create_pairing(CreatePairingRequest(session_id=session_id))["code"]
    claim_pairing(ClaimPairingRequest(code=code, worker_id="worker-1"))
    job_id = create_job(
        CreateJobRequest(
            session_id=session_id,
            worker_id="worker-1",
            quality_tier="general",
            reference_mode="url",
            reference_value="https://example.com/book",
        )
    )["job_id"]

    update_job_status(job_id, UpdateJobStatusRequest(status="extracting_audio"))
    update_job_status(job_id, UpdateJobStatusRequest(status="transcribing"))
    update_job_status(job_id, UpdateJobStatusRequest(status="uploading_artifacts"))
    attach_artifact(
        job_id,
        AttachArtifactRequest(
            kind="asr_txt",
            storage_path="data/jobs/job-1/intermediate/asr/source.txt",
            content_type="text/plain",
        ),
    )
    update_job_status(job_id, UpdateJobStatusRequest(status="queued_server"))

    payload = get_job(job_id, x_session_id=session_id)
    assert payload["status"] == "queued_server"
