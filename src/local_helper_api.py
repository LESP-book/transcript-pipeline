from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from src.config_loader import load_settings
from src.local_helper_protocol import CreateLocalJobRequest
from src.local_helper_service import LocalHelperService, LocalJobNotFoundError, LocalSessionAuthError
from src.local_job_runner import process_local_job
from src.pipeline_jobs import run_local_preprocess_job
from src.remote_http_client import RemoteApiClient


class LocalPairingClaimRequest(BaseModel):
    session_id: str
    worker_id: str
    local_session_secret: str


def create_app(
    service: LocalHelperService | None = None,
    *,
    remote_gateway=None,
    preprocess_executor=None,
) -> FastAPI:
    helper_service = service or LocalHelperService()
    app = FastAPI(title="transcript-pipeline local helper")

    @app.get("/v1/health")
    def health() -> dict[str, bool]:
        return helper_service.health()

    @app.get("/v1/runtime")
    def runtime() -> dict[str, str | bool]:
        payload = helper_service.runtime()
        return {
            "helper_version": payload.helper_version,
            "gpu_available": payload.gpu_available,
            "selected_runtime": payload.selected_runtime,
            "model_cache_ready": payload.model_cache_ready,
        }

    @app.post("/v1/pairing/claim")
    def claim_pairing(request: LocalPairingClaimRequest) -> dict[str, str | bool]:
        pairing = helper_service.claim_pairing(
            session_id=request.session_id,
            worker_id=request.worker_id,
            local_session_secret=request.local_session_secret,
        )
        return {
            "paired": True,
            "session_id": pairing.session_id,
            "worker_id": pairing.worker_id,
        }

    @app.post("/v1/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(request: CreateLocalJobRequest) -> dict[str, str | bool]:
        try:
            result = helper_service.create_job(request)
        except LocalSessionAuthError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        return {
            "local_job_id": result.local_job_id,
            "accepted": result.accepted,
            "message": result.message,
        }

    @app.get("/v1/jobs/{local_job_id}")
    def get_job(local_job_id: str) -> dict[str, str]:
        try:
            job = helper_service.get_job(local_job_id)
        except LocalJobNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {
            "local_job_id": job.local_job_id,
            "quality_tier": job.quality_tier,
            "video_handle": job.video_handle,
            "reference_mode": job.reference_mode,
            "reference_value": job.reference_value,
            "status": job.status,
            "remote_job_id": job.remote_job_id,
        }

    @app.post("/v1/jobs/{local_job_id}/process")
    def process_job(local_job_id: str) -> dict[str, str]:
        if remote_gateway is None or preprocess_executor is None:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="本地执行器尚未配置处理依赖。")
        try:
            process_local_job(
                local_job_id=local_job_id,
                helper_service=helper_service,
                remote_gateway=remote_gateway,
                preprocess_executor=preprocess_executor,
            )
            job = helper_service.get_job(local_job_id)
        except LocalJobNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {
            "local_job_id": job.local_job_id,
            "status": job.status,
            "remote_job_id": job.remote_job_id,
        }

    return app


def create_default_app() -> FastAPI:
    remote_api_base_url = os.getenv("TRANSCRIPT_REMOTE_API_BASE_URL", "http://127.0.0.1:8000")
    loaded_settings = load_settings(
        settings_path=os.getenv("TRANSCRIPT_SETTINGS_PATH"),
        profile_name=os.getenv("TRANSCRIPT_PROFILE"),
    )
    remote_gateway = RemoteApiClient(remote_api_base_url)
    return create_app(
        remote_gateway=remote_gateway,
        preprocess_executor=lambda quality_tier_name: run_local_preprocess_job(
            loaded_settings,
            quality_tier_name=quality_tier_name,
        ),
    )
