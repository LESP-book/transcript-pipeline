from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_ocr_pdf_books_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts/10_ocr_pdf_books.py"
    spec = importlib.util.spec_from_file_location("ocr_pdf_books_script", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载脚本模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_passes_paths_and_model_overrides_to_standalone_ocr(monkeypatch, tmp_path: Path) -> None:
    module = load_ocr_pdf_books_script_module()
    input_dir = tmp_path / "books"
    output_dir = tmp_path / "ocr-output"
    seen: dict[str, object] = {}
    logger = SimpleNamespace(info=lambda *_args, **_kwargs: None, error=lambda *_args, **_kwargs: None)
    loaded_settings = SimpleNamespace(
        settings=SimpleNamespace(runtime=SimpleNamespace(log_level="INFO")),
        active_profile_name="local_cpu",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "10_ocr_pdf_books.py",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--ocr-model",
            "gpt-5.6-terra",
            "--ocr-reasoning-effort",
            "high",
        ],
    )
    monkeypatch.setattr(module, "load_settings", lambda **_kwargs: loaded_settings)
    monkeypatch.setattr(module, "setup_logging", lambda _level: logger)

    def fake_apply_model_overrides(settings, overrides) -> None:
        seen["settings"] = settings
        seen["ocr_model"] = overrides.ocr_model
        seen["ocr_reasoning_effort"] = overrides.ocr_reasoning_effort

    def fake_ocr_pdf_book_batch(received_input_path, received_output_dir, settings):
        seen["input_path"] = received_input_path
        seen["output_dir"] = received_output_dir
        seen["batch_settings"] = settings
        return SimpleNamespace(
            items=[],
            failure_count=0,
        )

    monkeypatch.setattr(module, "apply_model_overrides", fake_apply_model_overrides)
    monkeypatch.setattr(module, "ocr_pdf_book_batch", fake_ocr_pdf_book_batch)
    monkeypatch.setattr(module, "summarize_pdf_book_ocr", lambda _summary: "total=0, success=0, failed=0")

    assert module.main() == 0
    assert seen["settings"] is loaded_settings
    assert seen["ocr_model"] == "gpt-5.6-terra"
    assert seen["ocr_reasoning_effort"] == "high"
    assert seen["input_path"] == input_dir
    assert seen["output_dir"] == output_dir
    assert seen["batch_settings"] is loaded_settings
