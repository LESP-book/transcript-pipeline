from __future__ import annotations

from dataclasses import dataclass, field

JOB_STATUS_ORDER = [
    "waiting_local",
    "extracting_audio",
    "transcribing",
    "uploading_artifacts",
    "queued_server",
    "preparing_reference",
    "ocr_processing",
    "refining",
    "exporting",
    "completed",
]
TERMINAL_JOB_STATUSES = {"completed", "failed", "expired"}
VALID_JOB_STATUSES = set(JOB_STATUS_ORDER) | TERMINAL_JOB_STATUSES
VALID_ARTIFACT_KINDS = {
    "asr_json",
    "asr_txt",
    "reference_file",
    "ocr_text",
    "refined_json",
    "final_markdown",
}
ALLOWED_ARTIFACT_KINDS_BY_STATUS = {
    "uploading_artifacts": {"asr_json", "asr_txt", "reference_file"},
    "ocr_processing": {"ocr_text"},
    "refining": {"refined_json"},
    "exporting": {"final_markdown"},
    "completed": {"asr_json", "asr_txt", "reference_file", "ocr_text", "refined_json", "final_markdown"},
}


class RemoteJobError(RuntimeError):
    """Raised when remote job metadata is invalid."""


class RemoteJobStatusError(RemoteJobError):
    """Raised when a remote job status transition is invalid."""


def _validate_status(status: str) -> str:
    normalized = status.strip()
    if normalized not in VALID_JOB_STATUSES:
        available = ", ".join(sorted(VALID_JOB_STATUSES))
        raise RemoteJobStatusError(f"未知任务状态: {normalized}. 可用状态: {available}")
    return normalized


def can_transition_job_status(current_status: str, next_status: str) -> bool:
    current = _validate_status(current_status)
    next_value = _validate_status(next_status)

    if current == next_value:
        return True
    if current in TERMINAL_JOB_STATUSES:
        return False
    if next_value in {"failed", "expired"}:
        return True

    try:
        current_index = JOB_STATUS_ORDER.index(current)
        next_index = JOB_STATUS_ORDER.index(next_value)
    except ValueError:
        return False
    return next_index == current_index + 1


def transition_job_status(current_status: str, next_status: str) -> str:
    if not can_transition_job_status(current_status, next_status):
        raise RemoteJobStatusError(f"非法任务状态流转: {current_status} -> {next_status}")
    return next_status.strip()


@dataclass(frozen=True)
class RemoteArtifact:
    kind: str
    storage_path: str
    content_type: str

    def __post_init__(self) -> None:
        if self.kind not in VALID_ARTIFACT_KINDS:
            available = ", ".join(sorted(VALID_ARTIFACT_KINDS))
            raise ValueError(f"不支持的任务产物类型: {self.kind}. 可用类型: {available}")


@dataclass
class RemoteJob:
    job_id: str
    session_id: str
    worker_id: str
    status: str
    artifacts: list[RemoteArtifact] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = _validate_status(self.status)

    def set_status(self, next_status: str) -> None:
        self.status = transition_job_status(self.status, next_status)

    def attach_artifact(self, artifact: RemoteArtifact) -> None:
        allowed_kinds = ALLOWED_ARTIFACT_KINDS_BY_STATUS.get(self.status, set())
        if artifact.kind not in allowed_kinds:
            allowed = ", ".join(sorted(allowed_kinds)) or "none"
            raise RemoteJobError(
                f"当前状态不允许挂载该产物: status={self.status}, kind={artifact.kind}, allowed={allowed}"
            )
        self.artifacts.append(artifact)
