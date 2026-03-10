from __future__ import annotations

from src.remote_jobs import (
    RemoteArtifact,
    RemoteJob,
    RemoteJobStatusError,
    can_transition_job_status,
    transition_job_status,
)


def test_can_transition_job_status_accepts_valid_forward_progress() -> None:
    assert can_transition_job_status("waiting_local", "extracting_audio") is True
    assert can_transition_job_status("uploading_artifacts", "queued_server") is True
    assert can_transition_job_status("refining", "exporting") is True
    assert can_transition_job_status("exporting", "completed") is True


def test_transition_job_status_rejects_invalid_jump() -> None:
    try:
        transition_job_status("waiting_local", "refining")
    except RemoteJobStatusError as exc:
        assert "非法任务状态流转" in str(exc)
    else:
        raise AssertionError("expected RemoteJobStatusError")


def test_remote_job_rejects_unknown_artifact_kind() -> None:
    try:
        RemoteArtifact(kind="video", storage_path="data/jobs/demo/input/video.mp4", content_type="video/mp4")
    except ValueError as exc:
        assert "不支持的任务产物类型" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_remote_job_allows_only_artifacts_matching_current_status() -> None:
    job = RemoteJob(job_id="job-1", session_id="session-1", worker_id="worker-1", status="uploading_artifacts")
    artifact = RemoteArtifact(
        kind="asr_txt",
        storage_path="data/jobs/job-1/intermediate/asr/source.txt",
        content_type="text/plain",
    )

    job.attach_artifact(artifact)

    assert job.artifacts == [artifact]
