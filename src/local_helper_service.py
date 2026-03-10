from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_hex

from src.local_helper_protocol import (
    CreateLocalJobRequest,
    CreateLocalJobResponse,
    HelperRuntimeStatus,
)


class LocalHelperError(RuntimeError):
    """Raised when local helper operations fail."""


class LocalSessionAuthError(LocalHelperError):
    """Raised when a localhost request carries an invalid session secret."""


class LocalJobNotFoundError(LocalHelperError):
    """Raised when a local helper job does not exist."""


@dataclass(frozen=True)
class LocalPairingState:
    session_id: str
    worker_id: str
    local_session_secret: str


@dataclass(frozen=True)
class LocalJobRecord:
    local_job_id: str
    quality_tier: str
    video_handle: str
    reference_mode: str
    reference_value: str
    status: str
    remote_job_id: str = ""


@dataclass
class LocalHelperService:
    runtime_status: HelperRuntimeStatus = field(
        default_factory=lambda: HelperRuntimeStatus(
            helper_version="0.1.0",
            gpu_available=False,
            selected_runtime="cpu",
            model_cache_ready=False,
        )
    )
    pairing_state: LocalPairingState | None = None
    jobs: dict[str, LocalJobRecord] = field(default_factory=dict)

    def health(self) -> dict[str, bool]:
        return {"ok": True, "paired": self.pairing_state is not None}

    def runtime(self) -> HelperRuntimeStatus:
        return self.runtime_status

    def claim_pairing(self, *, session_id: str, worker_id: str, local_session_secret: str) -> LocalPairingState:
        pairing = LocalPairingState(
            session_id=session_id,
            worker_id=worker_id,
            local_session_secret=local_session_secret,
        )
        self.pairing_state = pairing
        return pairing

    def create_job(self, request: CreateLocalJobRequest) -> CreateLocalJobResponse:
        if self.pairing_state is None or request.local_session_secret != self.pairing_state.local_session_secret:
            raise LocalSessionAuthError("本地会话密钥无效。")

        local_job_id = token_hex(8)
        self.jobs[local_job_id] = LocalJobRecord(
            local_job_id=local_job_id,
            quality_tier=request.quality_tier,
            video_handle=request.video_handle,
            reference_mode=request.reference_mode,
            reference_value=request.reference_value,
            status="accepted",
        )
        return CreateLocalJobResponse(local_job_id=local_job_id, accepted=True, message="accepted")

    def get_job(self, local_job_id: str) -> LocalJobRecord:
        job = self.jobs.get(local_job_id)
        if job is None:
            raise LocalJobNotFoundError(f"本地任务不存在: {local_job_id}")
        return job

    def update_job(
        self,
        local_job_id: str,
        *,
        status: str | None = None,
        remote_job_id: str | None = None,
    ) -> LocalJobRecord:
        job = self.get_job(local_job_id)
        updated = LocalJobRecord(
            local_job_id=job.local_job_id,
            quality_tier=job.quality_tier,
            video_handle=job.video_handle,
            reference_mode=job.reference_mode,
            reference_value=job.reference_value,
            status=status or job.status,
            remote_job_id=remote_job_id if remote_job_id is not None else job.remote_job_id,
        )
        self.jobs[local_job_id] = updated
        return updated
