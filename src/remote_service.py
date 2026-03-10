from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_hex

from src.remote_jobs import RemoteArtifact, RemoteJob


class RemoteServiceError(RuntimeError):
    """Raised when remote coordination service operations fail."""


class SessionNotFoundError(RemoteServiceError):
    """Raised when a session does not exist."""


class PairingCodeNotFoundError(RemoteServiceError):
    """Raised when a pairing code does not exist."""


class PairingCodeAlreadyClaimedError(RemoteServiceError):
    """Raised when a pairing code has already been claimed."""


class RemoteOwnershipError(RemoteServiceError):
    """Raised when a job is accessed from a different session."""


@dataclass(frozen=True)
class AnonymousSession:
    session_id: str


@dataclass(frozen=True)
class PairingCode:
    code: str
    session_id: str
    status: str
    worker_id: str = ""
    local_session_secret: str = ""


@dataclass
class RemoteCoordinationService:
    sessions: dict[str, AnonymousSession] = field(default_factory=dict)
    pairings: dict[str, PairingCode] = field(default_factory=dict)
    jobs: dict[str, RemoteJob] = field(default_factory=dict)

    def create_anonymous_session(self) -> AnonymousSession:
        session = AnonymousSession(session_id=token_hex(12))
        self.sessions[session.session_id] = session
        return session

    def create_pairing_code(self, session_id: str) -> PairingCode:
        self._require_session(session_id)
        pairing = PairingCode(code=token_hex(4), session_id=session_id, status="pending")
        self.pairings[pairing.code] = pairing
        return pairing

    def claim_pairing_code(self, code: str, *, worker_id: str) -> PairingCode:
        pairing = self.pairings.get(code)
        if pairing is None:
            raise PairingCodeNotFoundError(f"配对码不存在: {code}")
        if pairing.status != "pending":
            raise PairingCodeAlreadyClaimedError(f"配对码已被使用: {code}")

        claimed = PairingCode(
            code=pairing.code,
            session_id=pairing.session_id,
            status="claimed",
            worker_id=worker_id,
            local_session_secret=token_hex(16),
        )
        self.pairings[code] = claimed
        return claimed

    def create_job(
        self,
        *,
        session_id: str,
        worker_id: str,
        quality_tier: str,
        reference_mode: str,
        reference_value: str,
    ) -> RemoteJob:
        self._require_session(session_id)
        job = RemoteJob(
            job_id=token_hex(8),
            session_id=session_id,
            worker_id=worker_id,
            status="waiting_local",
        )
        self.jobs[job.job_id] = job
        return job

    def list_jobs_for_session(self, session_id: str) -> list[RemoteJob]:
        self._require_session(session_id)
        return [job for job in self.jobs.values() if job.session_id == session_id]

    def get_job_for_session(self, session_id: str, job_id: str) -> RemoteJob:
        self._require_session(session_id)
        job = self.jobs[job_id]
        if job.session_id != session_id:
            raise RemoteOwnershipError(f"任务不属于当前会话: {job_id}")
        return job

    def update_job_status(self, job_id: str, next_status: str) -> RemoteJob:
        job = self.jobs[job_id]
        job.set_status(next_status)
        return job

    def attach_artifact(self, job_id: str, artifact: RemoteArtifact) -> RemoteJob:
        job = self.jobs[job_id]
        job.attach_artifact(artifact)
        return job

    def _require_session(self, session_id: str) -> AnonymousSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"匿名会话不存在: {session_id}")
        return session
