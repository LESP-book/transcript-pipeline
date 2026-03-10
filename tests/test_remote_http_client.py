from __future__ import annotations

from src.remote_http_client import RemoteApiClient


class FakeResponse:
    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return self._payload


class FakeHttpxClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict) -> FakeResponse:
        self.calls.append((url, json))
        if url.endswith("/api/helper/jobs"):
            return FakeResponse({"job_id": "remote-1"})
        return FakeResponse({"status": json.get("status", ""), "artifact_kind": json.get("kind", "")})

    def close(self) -> None:
        return None


def test_remote_api_client_calls_expected_endpoints() -> None:
    transport = FakeHttpxClient()
    client = RemoteApiClient("http://remote.test", http_client=transport)

    job_id = client.create_job(
        session_id="session-1",
        worker_id="worker-1",
        quality_tier="high",
        reference_mode="url",
        reference_value="https://example.com/book",
    )
    client.update_job_status(job_id, "extracting_audio")
    client.attach_artifact(job_id, "asr_txt", "data/jobs/job-1/source.txt", "text/plain")

    assert job_id == "remote-1"
    assert transport.calls == [
        (
            "http://remote.test/api/helper/jobs",
            {
                "session_id": "session-1",
                "worker_id": "worker-1",
                "quality_tier": "high",
                "reference_mode": "url",
                "reference_value": "https://example.com/book",
            },
        ),
        (
            "http://remote.test/api/helper/jobs/remote-1/status",
            {"status": "extracting_audio"},
        ),
        (
            "http://remote.test/api/helper/jobs/remote-1/artifacts",
            {
                "kind": "asr_txt",
                "storage_path": "data/jobs/job-1/source.txt",
                "content_type": "text/plain",
            },
        ),
    ]
