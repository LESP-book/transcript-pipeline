from __future__ import annotations

from typing import Callable, Protocol

from src.local_helper_service import LocalHelperService
from src.pipeline_jobs import LocalPreprocessResult


class RemoteJobGateway(Protocol):
    def create_job(self, *, session_id: str, worker_id: str, quality_tier: str, reference_mode: str, reference_value: str) -> str: ...

    def update_job_status(self, job_id: str, status: str) -> None: ...

    def attach_artifact(self, job_id: str, kind: str, storage_path: str, content_type: str) -> None: ...


def process_local_job(
    *,
    local_job_id: str,
    helper_service: LocalHelperService,
    remote_gateway: RemoteJobGateway,
    preprocess_executor: Callable[[str], LocalPreprocessResult],
) -> None:
    local_job = helper_service.get_job(local_job_id)
    pairing = helper_service.pairing_state
    if pairing is None:
        raise RuntimeError("本地助手尚未完成配对。")

    remote_job_id = remote_gateway.create_job(
        session_id=pairing.session_id,
        worker_id=pairing.worker_id,
        quality_tier=local_job.quality_tier,
        reference_mode=local_job.reference_mode,
        reference_value=local_job.reference_value,
    )

    helper_service.update_job(local_job_id, status="extracting_audio", remote_job_id=remote_job_id)
    remote_gateway.update_job_status(remote_job_id, "extracting_audio")

    preprocess_result = preprocess_executor(local_job.quality_tier)

    helper_service.update_job(local_job_id, status="transcribing")
    remote_gateway.update_job_status(remote_job_id, "transcribing")

    helper_service.update_job(local_job_id, status="uploading_artifacts")
    remote_gateway.update_job_status(remote_job_id, "uploading_artifacts")

    for item in preprocess_result.transcribed_audio:
        remote_gateway.attach_artifact(remote_job_id, "asr_json", str(item.output_paths.json_path), "application/json")
        remote_gateway.attach_artifact(remote_job_id, "asr_txt", str(item.output_paths.txt_path), "text/plain")

    if local_job.reference_mode == "local_file":
        remote_gateway.attach_artifact(
            remote_job_id,
            "reference_file",
            local_job.reference_value,
            "application/octet-stream",
        )

    helper_service.update_job(local_job_id, status="queued_server")
    remote_gateway.update_job_status(remote_job_id, "queued_server")
