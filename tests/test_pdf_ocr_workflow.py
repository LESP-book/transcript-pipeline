from pathlib import Path

from src.config_loader import load_settings
from src.pdf_ocr_workflow import (
    PDFOCRPageState,
    build_pdf_ocr_checkpoint_namespace,
    build_pdf_ocr_run_identity,
)
from tests.helpers import write_minimal_settings


def test_pdf_ocr_run_identity_is_stable_and_configuration_sensitive(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"same pdf content")
    config_path = write_minimal_settings(
        tmp_path,
        reference_overrides={
            "codex_ocr_model": "gpt-5.4-mini",
            "codex_ocr_reasoning_effort": "high",
        },
    )
    loaded_settings = load_settings(settings_path=config_path, project_root=tmp_path)

    first = build_pdf_ocr_run_identity(source, loaded_settings)
    second = build_pdf_ocr_run_identity(source, loaded_settings)
    assert first == second
    assert first.fingerprint == second.fingerprint

    loaded_settings.settings.reference.codex_ocr_model = "gpt-5.6-terra"
    model_changed = build_pdf_ocr_run_identity(source, loaded_settings)
    assert model_changed.fingerprint != first.fingerprint

    loaded_settings.settings.reference.codex_ocr_model = "gpt-5.4-mini"
    loaded_settings.settings.reference.codex_ocr_reasoning_effort = "medium"
    reasoning_changed = build_pdf_ocr_run_identity(source, loaded_settings)
    assert reasoning_changed.fingerprint != first.fingerprint

    source.write_bytes(b"replaced pdf content")
    source_changed = build_pdf_ocr_run_identity(source, loaded_settings)
    assert source_changed.source_digest != first.source_digest
    assert source_changed.fingerprint != reasoning_changed.fingerprint


def test_pdf_ocr_checkpoint_namespace_uses_full_identity_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"pdf")
    config_path = write_minimal_settings(tmp_path)
    loaded_settings = load_settings(settings_path=config_path, project_root=tmp_path)
    identity = build_pdf_ocr_run_identity(source, loaded_settings)

    namespace = build_pdf_ocr_checkpoint_namespace(tmp_path / "pages", identity)

    assert namespace == (tmp_path / "pages" / identity.fingerprint).resolve()


def test_pdf_ocr_page_state_exposes_shared_progress_contract() -> None:
    state = PDFOCRPageState(
        page_count=3,
        completed_page_numbers=(1, 3),
        page_errors={2: "upstream_unavailable"},
    )

    assert state.completed_pages == 2
    assert state.failed_page_numbers == (2,)
    assert state.resumable is True
