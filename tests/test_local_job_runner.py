from __future__ import annotations

from pathlib import Path

from src.asr_utils import AsrBatchItem, AsrOutputPaths
from src.ffmpeg_utils import AudioExtractionResult
from src.local_helper_protocol import CreateLocalJobRequest
from src.local_helper_service import LocalHelperService
from src.local_job_runner import process_local_job
from src.pipeline_jobs import LocalPreprocessResult


class FakeRemoteGateway:
    def __init__(self) -> None:
        self.created_jobs: list[dict] = []
        self.status_updates: list[tuple[str, str]] = []
        self.artifacts: list[tuple[str, str]] = []

    def create_job(self, *, session_id: str, worker_id: str, quality_tier: str, reference_mode: str, reference_value: str) -> str:
        self.created_jobs.append(
            {
                "session_id": session_id,
                "worker_id": worker_id,
                "quality_tier": quality_tier,
                "reference_mode": reference_mode,
                "reference_value": reference_value,
            }
        )
        return "remote-job-1"

    def update_job_status(self, job_id: str, status: str) -> None:
        self.status_updates.append((job_id, status))

    def attach_artifact(self, job_id: str, kind: str, storage_path: str, content_type: str) -> None:
        _ = content_type
        self.artifacts.append((job_id, kind, storage_path))


def test_process_local_job_pushes_status_and_artifacts(tmp_path: Path) -> None:
    service = LocalHelperService()
    service.claim_pairing(session_id="session-1", worker_id="worker-1", local_session_secret="secret-1")
    created = service.create_job(
        CreateLocalJobRequest(
            quality_tier="high",
            video_handle="video-1",
            reference_mode="local_file",
            reference_value="chapter.pdf",
            local_session_secret="secret-1",
        )
    )

    asr_dir = tmp_path / "asr"
    asr_dir.mkdir(parents=True, exist_ok=True)
    asr_json = asr_dir / "source.json"
    asr_txt = asr_dir / "source.txt"
    asr_json.write_text("{}", encoding="utf-8")
    asr_txt.write_text("正文", encoding="utf-8")

    preprocess_result = LocalPreprocessResult(
        quality_tier_name="high",
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

    gateway = FakeRemoteGateway()

    process_local_job(
        local_job_id=created.local_job_id,
        helper_service=service,
        remote_gateway=gateway,
        preprocess_executor=lambda quality_tier_name: preprocess_result,
    )

    job = service.get_job(created.local_job_id)
    assert job.status == "queued_server"
    assert job.remote_job_id == "remote-job-1"
    assert gateway.status_updates == [
        ("remote-job-1", "extracting_audio"),
        ("remote-job-1", "transcribing"),
        ("remote-job-1", "uploading_artifacts"),
        ("remote-job-1", "queued_server"),
    ]
    assert ("remote-job-1", "asr_json", str(asr_json)) in gateway.artifacts
    assert ("remote-job-1", "asr_txt", str(asr_txt)) in gateway.artifacts
    assert ("remote-job-1", "reference_file", "chapter.pdf") in gateway.artifacts
