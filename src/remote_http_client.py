from __future__ import annotations

import httpx


class RemoteApiClient:
    def __init__(self, base_url: str, *, http_client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=30.0)

    def create_job(
        self,
        *,
        session_id: str,
        worker_id: str,
        quality_tier: str,
        reference_mode: str,
        reference_value: str,
    ) -> str:
        response = self._client.post(
            f"{self.base_url}/api/helper/jobs",
            json={
                "session_id": session_id,
                "worker_id": worker_id,
                "quality_tier": quality_tier,
                "reference_mode": reference_mode,
                "reference_value": reference_value,
            },
        )
        response.raise_for_status()
        return str(response.json()["job_id"])

    def update_job_status(self, job_id: str, status: str) -> None:
        response = self._client.post(
            f"{self.base_url}/api/helper/jobs/{job_id}/status",
            json={"status": status},
        )
        response.raise_for_status()

    def attach_artifact(self, job_id: str, kind: str, storage_path: str, content_type: str) -> None:
        response = self._client.post(
            f"{self.base_url}/api/helper/jobs/{job_id}/artifacts",
            json={
                "kind": kind,
                "storage_path": storage_path,
                "content_type": content_type,
            },
        )
        response.raise_for_status()

    def close(self) -> None:
        self._client.close()
