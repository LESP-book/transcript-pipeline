from __future__ import annotations

from src.remote_service import (
    PairingCodeAlreadyClaimedError,
    PairingCodeNotFoundError,
    RemoteCoordinationService,
    RemoteOwnershipError,
)


def test_create_anonymous_session_and_pairing_code() -> None:
    service = RemoteCoordinationService()

    session = service.create_anonymous_session()
    pairing = service.create_pairing_code(session.session_id)

    assert session.session_id
    assert pairing.session_id == session.session_id
    assert pairing.status == "pending"


def test_claim_pairing_code_binds_worker_and_returns_local_secret() -> None:
    service = RemoteCoordinationService()
    session = service.create_anonymous_session()
    pairing = service.create_pairing_code(session.session_id)

    claimed = service.claim_pairing_code(pairing.code, worker_id="worker-1")

    assert claimed.worker_id == "worker-1"
    assert claimed.status == "claimed"
    assert claimed.local_session_secret


def test_claim_pairing_code_rejects_second_claim() -> None:
    service = RemoteCoordinationService()
    session = service.create_anonymous_session()
    pairing = service.create_pairing_code(session.session_id)
    service.claim_pairing_code(pairing.code, worker_id="worker-1")

    try:
        service.claim_pairing_code(pairing.code, worker_id="worker-2")
    except PairingCodeAlreadyClaimedError:
        pass
    else:
        raise AssertionError("expected PairingCodeAlreadyClaimedError")


def test_create_job_and_list_only_session_owned_jobs() -> None:
    service = RemoteCoordinationService()
    session_a = service.create_anonymous_session()
    session_b = service.create_anonymous_session()
    pairing_a = service.create_pairing_code(session_a.session_id)
    service.claim_pairing_code(pairing_a.code, worker_id="worker-a")

    job = service.create_job(
        session_id=session_a.session_id,
        worker_id="worker-a",
        quality_tier="high",
        reference_mode="url",
        reference_value="https://example.com/book",
    )

    jobs_a = service.list_jobs_for_session(session_a.session_id)
    jobs_b = service.list_jobs_for_session(session_b.session_id)

    assert [item.job_id for item in jobs_a] == [job.job_id]
    assert jobs_b == []


def test_update_job_status_rejects_wrong_session() -> None:
    service = RemoteCoordinationService()
    session_a = service.create_anonymous_session()
    session_b = service.create_anonymous_session()
    pairing_a = service.create_pairing_code(session_a.session_id)
    service.claim_pairing_code(pairing_a.code, worker_id="worker-a")
    job = service.create_job(
        session_id=session_a.session_id,
        worker_id="worker-a",
        quality_tier="general",
        reference_mode="local_file",
        reference_value="source.pdf",
    )

    try:
        service.get_job_for_session(session_b.session_id, job.job_id)
    except RemoteOwnershipError:
        pass
    else:
        raise AssertionError("expected RemoteOwnershipError")


def test_update_job_status_advances_job() -> None:
    service = RemoteCoordinationService()
    session = service.create_anonymous_session()
    pairing = service.create_pairing_code(session.session_id)
    service.claim_pairing_code(pairing.code, worker_id="worker-1")
    job = service.create_job(
        session_id=session.session_id,
        worker_id="worker-1",
        quality_tier="max",
        reference_mode="local_file",
        reference_value="chapter.pdf",
    )

    updated = service.update_job_status(job.job_id, "extracting_audio")

    assert updated.status == "extracting_audio"


def test_claim_pairing_code_rejects_unknown_code() -> None:
    service = RemoteCoordinationService()

    try:
        service.claim_pairing_code("unknown", worker_id="worker-1")
    except PairingCodeNotFoundError:
        pass
    else:
        raise AssertionError("expected PairingCodeNotFoundError")
