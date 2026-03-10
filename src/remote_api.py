from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from src.remote_jobs import RemoteArtifact, RemoteJobError, RemoteJobStatusError
from src.remote_service import (
    PairingCodeAlreadyClaimedError,
    PairingCodeNotFoundError,
    RemoteCoordinationService,
    RemoteOwnershipError,
    SessionNotFoundError,
)


class CreatePairingRequest(BaseModel):
    session_id: str


class ClaimPairingRequest(BaseModel):
    code: str
    worker_id: str


class CreateJobRequest(BaseModel):
    session_id: str
    worker_id: str
    quality_tier: str
    reference_mode: str
    reference_value: str


class UpdateJobStatusRequest(BaseModel):
    status: str


class AttachArtifactRequest(BaseModel):
    kind: str
    storage_path: str
    content_type: str


def create_app(service: RemoteCoordinationService | None = None) -> FastAPI:
    coordination_service = service or RemoteCoordinationService()
    app = FastAPI(title="transcript-pipeline remote api")

    @app.post("/api/anonymous-sessions", status_code=status.HTTP_201_CREATED)
    def create_anonymous_session() -> dict[str, str]:
        session = coordination_service.create_anonymous_session()
        return {"session_id": session.session_id}

    @app.post("/api/pairings", status_code=status.HTTP_201_CREATED)
    def create_pairing_code(request: CreatePairingRequest) -> dict[str, str]:
        try:
            pairing = coordination_service.create_pairing_code(request.session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {"code": pairing.code, "session_id": pairing.session_id, "status": pairing.status}

    @app.post("/api/helper/pairings/claim")
    def claim_pairing_code(request: ClaimPairingRequest) -> dict[str, str]:
        try:
            claimed = coordination_service.claim_pairing_code(request.code, worker_id=request.worker_id)
        except PairingCodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except PairingCodeAlreadyClaimedError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return {
            "code": claimed.code,
            "session_id": claimed.session_id,
            "worker_id": claimed.worker_id,
            "status": claimed.status,
            "local_session_secret": claimed.local_session_secret,
        }

    @app.post("/api/helper/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(request: CreateJobRequest) -> dict[str, str]:
        try:
            job = coordination_service.create_job(
                session_id=request.session_id,
                worker_id=request.worker_id,
                quality_tier=request.quality_tier,
                reference_mode=request.reference_mode,
                reference_value=request.reference_value,
            )
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {"job_id": job.job_id, "status": job.status}

    @app.get("/api/jobs")
    def list_jobs(x_session_id: str = Header(..., alias="X-Session-Id")) -> dict[str, list[dict[str, str]]]:
        try:
            jobs = coordination_service.list_jobs_for_session(x_session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        return {
            "items": [
                {
                    "job_id": job.job_id,
                    "worker_id": job.worker_id,
                    "status": job.status,
                }
                for job in jobs
            ]
        }

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, x_session_id: str = Header(..., alias="X-Session-Id")) -> dict[str, str]:
        try:
            job = coordination_service.get_job_for_session(x_session_id, job_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except RemoteOwnershipError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

        return {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "worker_id": job.worker_id,
            "status": job.status,
        }

    @app.post("/api/helper/jobs/{job_id}/status")
    def update_job_status(job_id: str, request: UpdateJobStatusRequest) -> dict[str, str]:
        try:
            job = coordination_service.update_job_status(job_id, request.status)
        except RemoteJobStatusError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return {"job_id": job.job_id, "status": job.status}

    @app.post("/api/helper/jobs/{job_id}/artifacts")
    def attach_artifact(job_id: str, request: AttachArtifactRequest) -> dict[str, str]:
        try:
            job = coordination_service.attach_artifact(
                job_id,
                RemoteArtifact(
                    kind=request.kind,
                    storage_path=request.storage_path,
                    content_type=request.content_type,
                ),
            )
        except (RemoteJobError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return {"job_id": job.job_id, "status": job.status, "artifact_kind": request.kind}

    return app


def create_default_app() -> FastAPI:
    return create_app()
