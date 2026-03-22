from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.reference_utils import (
    CodexOCRError,
    GeminiOCRError,
    ReferenceInputEmptyError,
    build_reference_output_paths,
    is_effectively_empty_text,
    iter_reference_files,
    prepare_reference_file,
    read_text_file,
    run_codex_pdf_ocr,
    sanitize_ocrmypdf_text,
    sanitize_gemini_ocr_text,
    run_gemini_pdf_ocr,
)
from tests.helpers import write_minimal_settings


def test_prepare_reference_batch_raises_when_reference_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    (tmp_path / "data/input/reference").mkdir(parents=True, exist_ok=True)

    loaded_settings = load_settings(project_root=tmp_path)

    from src.reference_utils import prepare_reference_batch

    with pytest.raises(ReferenceInputEmptyError):
        prepare_reference_batch(loaded_settings)


def test_read_text_file_for_txt(tmp_path: Path) -> None:
    source = tmp_path / "chapter01.txt"
    source.write_text("第一段\n第二段", encoding="utf-8")

    assert read_text_file(source) == "第一段\n第二段"


def test_read_markdown_file_via_prepare_reference_file(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "outline.md"
    source.write_text("# 标题\n\n正文", encoding="utf-8")

    loaded_settings = load_settings(project_root=tmp_path)
    result = prepare_reference_file(source, loaded_settings)

    assert result.source_type == "md"
    assert result.success is True
    assert "# 标题" in result.extracted_text


def test_iter_reference_files_filters_supported_extensions(tmp_path: Path) -> None:
    (tmp_path / "book.txt").write_text("txt", encoding="utf-8")
    (tmp_path / "notes.MD").write_text("md", encoding="utf-8")
    (tmp_path / "scan.pdf").write_text("pdf", encoding="utf-8")
    (tmp_path / "image.png").write_text("png", encoding="utf-8")

    files = iter_reference_files(tmp_path, [".txt", ".md", ".pdf"])

    assert [path.name for path in files] == ["book.txt", "notes.MD", "scan.pdf"]


def test_build_reference_output_paths_uses_reference_basename(tmp_path: Path) -> None:
    reference_path = tmp_path / "chapter-03.pdf"
    output_dir = tmp_path / "data/intermediate/extracted_text"

    output_paths = build_reference_output_paths(reference_path, output_dir)

    assert output_paths.txt_path == output_dir / "chapter-03.txt"
    assert output_paths.json_path == output_dir / "chapter-03.json"


def test_is_effectively_empty_text_uses_content_length_threshold() -> None:
    assert is_effectively_empty_text("")
    assert is_effectively_empty_text(" \n ")
    assert not is_effectively_empty_text("这是足够长的可提取文字内容")


def test_prepare_reference_file_uses_ocr_fallback_when_pdf_text_layer_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.run_gemini_pdf_ocr",
        lambda _path, _settings: ("这是 Gemini OCR 提取出来的中文文本内容。", ["PDF 文字层为空，已使用 Gemini OCR fallback。model=gemini-3-flash-preview"]),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "gemini_cli_pdf_ocr"
    assert "Gemini OCR fallback" in " ".join(result.warnings)
    assert "Gemini OCR 提取出来的中文文本内容" in result.extracted_text


def test_prepare_reference_file_prefers_gemini_ocr_even_when_pdf_has_text_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "book.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.run_gemini_pdf_ocr",
        lambda _path, _settings: ("这是 Gemini 优先 OCR 的结果。", ["已优先使用 Gemini OCR。model=gemini-3-flash-preview"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("这是 PDF 文字层内容。", []),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "gemini_cli_pdf_ocr"
    assert "Gemini 优先 OCR 的结果" in result.extracted_text
    assert "优先使用 Gemini OCR" in " ".join(result.warnings)


def test_prepare_reference_file_falls_back_to_text_layer_when_gemini_ocr_fails_and_pdf_has_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "book.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    def fake_gemini_ocr(_path: Path, _settings) -> tuple[str, list[str]]:
        raise GeminiOCRError("capacity exhausted")

    monkeypatch.setattr("src.reference_utils.run_gemini_pdf_ocr", fake_gemini_ocr)
    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("这是 PDF 文字层内容。", []),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "pypdf_text_extract"
    assert "Gemini OCR 失败，已回退到 PDF 文字层提取" in " ".join(result.warnings)
    assert result.extracted_text == "这是 PDF 文字层内容。"


def test_prepare_reference_file_falls_back_to_codex_ocr_when_gemini_ocr_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )

    def fake_gemini_ocr(_path: Path, _settings) -> tuple[str, list[str]]:
        raise GeminiOCRError("network close")

    monkeypatch.setattr("src.reference_utils.run_gemini_pdf_ocr", fake_gemini_ocr)
    monkeypatch.setattr(
        "src.reference_utils.run_codex_pdf_ocr",
        lambda _path, _settings: ("这是 Codex OCR 提取出来的中文文本内容。", ["PDF 文字层为空，已使用 Codex OCR fallback。model=gpt-5.4-mini"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.run_tesseract_pdf_ocr",
        lambda _path, _settings: pytest.fail("不应直接退回 ocrmypdf"),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "codex_cli_pdf_ocr"
    assert "Gemini OCR 失败，已回退到 Codex OCR" in " ".join(result.warnings)
    assert "Codex OCR 提取出来的中文文本内容" in result.extracted_text


def test_prepare_reference_file_falls_back_to_ocrmypdf_when_codex_ocr_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": True})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )

    def fake_gemini_ocr(_path: Path, _settings) -> tuple[str, list[str]]:
        raise GeminiOCRError("network close")

    def fake_codex_ocr(_path: Path, _settings) -> tuple[str, list[str]]:
        raise CodexOCRError("codex cli timeout")

    monkeypatch.setattr("src.reference_utils.run_gemini_pdf_ocr", fake_gemini_ocr)
    monkeypatch.setattr("src.reference_utils.run_codex_pdf_ocr", fake_codex_ocr)
    monkeypatch.setattr(
        "src.reference_utils.run_tesseract_pdf_ocr",
        lambda _path, _settings: ("这是 ocrmypdf OCR 提取出来的中文文本内容。", ["PDF 文字层为空，已使用 OCR fallback。backend=ocrmypdf_tesseract"]),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is True
    assert result.extraction_method == "ocrmypdf_tesseract"
    assert "Gemini OCR 和 Codex OCR 都失败，已回退到 ocrmypdf" in " ".join(result.warnings)
    assert "ocrmypdf OCR 提取出来的中文文本内容" in result.extracted_text


def test_prepare_reference_file_keeps_pdf_failure_when_ocr_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, reference_overrides={"run_ocr_when_needed": False})
    reference_dir = tmp_path / "data/input/reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    source = reference_dir / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    loaded_settings = load_settings(project_root=tmp_path)

    monkeypatch.setattr(
        "src.reference_utils.extract_pdf_text",
        lambda _path: ("", ["PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。"]),
    )
    monkeypatch.setattr(
        "src.reference_utils.run_gemini_pdf_ocr",
        lambda _path, _settings: (_ for _ in ()).throw(GeminiOCRError("disabled in test")),
    )

    result = prepare_reference_file(source, loaded_settings)

    assert result.success is False
    assert result.extraction_method == "pypdf_text_extract"
    assert result.warnings == [
        "Gemini OCR 失败，且当前未启用 OCR fallback。reason=disabled in test",
        "PDF 提取结果为空或接近空，可能是扫描版 PDF；当前阶段未启用 OCR。",
    ]


def test_run_gemini_pdf_ocr_stages_pdf_into_isolated_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    source = tmp_path / "external" / "scan.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4 fake")

    seen: dict[str, object] = {}

    def fake_run(command, *, text, capture_output, cwd, timeout, check):
        seen["command"] = command
        seen["cwd"] = cwd
        seen["timeout"] = timeout

        class Completed:
            returncode = 0
            stdout = "这是 Gemini OCR 的结果。"
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.reference_utils.shutil.which", lambda _name: "/usr/bin/gemini")
    monkeypatch.setattr("src.reference_utils.subprocess.run", fake_run)

    text, warnings = run_gemini_pdf_ocr(source, loaded_settings)

    command = seen["command"]
    assert isinstance(command, list)
    assert text == "这是 Gemini OCR 的结果。"
    assert "Gemini OCR fallback" in " ".join(warnings)
    assert command[2] == loaded_settings.settings.reference.gemini_ocr_model
    assert seen["cwd"] != str(tmp_path)
    assert seen["timeout"] == loaded_settings.settings.reference.ocr_timeout_seconds
    assert str(seen["cwd"]).startswith(str(loaded_settings.path_for("ocr_dir")))
    staged_pdf = Path(str(seen["cwd"])) / source.name
    assert staged_pdf.exists()
    assert staged_pdf.read_bytes() == source.read_bytes()
    assert f"@{{{source.name}}}" in command[-1]
    assert str(source) not in command[-1]


def test_run_codex_pdf_ocr_uses_configured_model_prompt_and_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(
        tmp_path,
        reference_overrides={"codex_ocr_model": "gpt-5.4-mini", "codex_ocr_reasoning_effort": "medium"},
    )
    loaded_settings = load_settings(project_root=tmp_path)

    source = tmp_path / "external" / "scan.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4 fake")

    seen: dict[str, object] = {}

    def fake_run(command, *, input, text, capture_output, cwd, timeout, check):
        seen["command"] = command
        seen["input"] = input
        seen["cwd"] = cwd
        seen["timeout"] = timeout
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("这是 Codex OCR 的结果。", encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.reference_utils.shutil.which", lambda name: "/usr/bin/codex" if name == "codex" else None)
    monkeypatch.setattr("src.reference_utils.subprocess.run", fake_run)

    text, warnings = run_codex_pdf_ocr(source, loaded_settings)

    command = seen["command"]
    assert isinstance(command, list)
    assert text == "这是 Codex OCR 的结果。"
    assert "Codex OCR fallback" in " ".join(warnings)
    assert command[:4] == ["codex", "exec", "-C", str(Path(str(seen["cwd"])).resolve())]
    assert ["-m", "gpt-5.4-mini"] == command[6:8]
    assert '-c' in command
    assert 'model_reasoning_effort="medium"' in command
    assert seen["timeout"] == loaded_settings.settings.reference.ocr_timeout_seconds
    assert "禁止调用本机的 OCR 工具" in str(seen["input"])
    assert "只使用模型自身的视觉能力" in str(seen["input"])
    assert f"@{{{source.name}}}" in str(seen["input"])


def test_run_gemini_pdf_ocr_uses_reference_fallback_model_only_for_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(
        tmp_path,
        reference_overrides={"gemini_ocr_model": "gemini-3-flash-preview", "gemini_ocr_fallback_model": "gemini-2.5-flash"},
        llm_overrides={"gemini_model": "gemini-3.1-pro-preview", "gemini_fallback_model": "gemini-3-flash-preview"},
    )
    loaded_settings = load_settings(project_root=tmp_path)

    source = tmp_path / "external" / "scan.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4 fake")

    commands: list[list[str]] = []

    def fake_run(command, *, text, capture_output, cwd, timeout, check):
        commands.append(command)

        class Completed:
            def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        if command[2] == "gemini-3-flash-preview":
            return Completed(1, "", "429 MODEL_CAPACITY_EXHAUSTED")
        return Completed(0, "这是 Gemini OCR 的结果。", "")

    monkeypatch.setattr("src.reference_utils.shutil.which", lambda _name: "/usr/bin/gemini")
    monkeypatch.setattr("src.reference_utils.subprocess.run", fake_run)

    text, warnings = run_gemini_pdf_ocr(source, loaded_settings)

    assert text == "这是 Gemini OCR 的结果。"
    assert commands == [
        ["gemini", "-m", "gemini-3-flash-preview", "-p", commands[0][4]],
        ["gemini", "-m", "gemini-2.5-flash", "-p", commands[1][4]],
    ]
    assert "model=gemini-2.5-flash" in " ".join(warnings)


def test_sanitize_gemini_ocr_text_removes_leakage_page_markers_and_tail_repetition() -> None:
    raw_text = """
t>...
CRITICAL INSTRUCTION 2: ...'

Now I have the text content of the PDF.
我将读取 PDF 文件并提取纯文本。

[Page 1]
t第二节 巩固国家统一的重要政策措施

秦始皇坚持法家政治路线。
201

[Page 2]
地主阶级专政进一步加强。
202

OK, I will output purely the text from these pages.
Page 1:
第二节 巩固国家统一的重要政策措施
""".strip()

    assert sanitize_gemini_ocr_text(raw_text) == (
        "第二节 巩固国家统一的重要政策措施\n\n"
        "秦始皇坚持法家政治路线。\n\n"
        "地主阶级专政进一步加强。"
    )


def test_run_gemini_pdf_ocr_sanitizes_model_output_before_return_and_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    source = tmp_path / "external" / "scan.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4 fake")

    polluted_output = """
CRITICAL INSTRUCTION 2: ...'
[Page 1]
第二节 巩固国家统一的重要政策措施
201

OK, I will output purely the text from these pages.
""".strip()

    def fake_run(_command, *, text, capture_output, cwd, timeout, check):
        class Completed:
            returncode = 0
            stdout = polluted_output
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.reference_utils.shutil.which", lambda _name: "/usr/bin/gemini")
    monkeypatch.setattr("src.reference_utils.subprocess.run", fake_run)

    text, _warnings = run_gemini_pdf_ocr(source, loaded_settings)

    sidecar_path = loaded_settings.path_for("ocr_dir") / f"{source.stem}.gemini_ocr.txt"
    assert text == "第二节 巩固国家统一的重要政策措施"
    assert sidecar_path.read_text(encoding="utf-8") == "第二节 巩固国家统一的重要政策措施"


def test_sanitize_ocrmypdf_text_removes_repeated_headers_footers_and_page_numbers() -> None:
    raw_text = (
        "附一，中国革命的社会意义 395\n"
        "第一段 正文内容。\n"
        "326\n"
        "\f"
        "附一，中国革命的社会意义 396\n"
        "第二段   正文内容。\n"
        "327\n"
        "\f"
        "附一，中国革命的社会意义 397\n"
        "第三段 正文内容。\n"
        "328\n"
    )

    assert sanitize_ocrmypdf_text(raw_text) == (
        "第一段 正文内容。\n\n"
        "第二段 正文内容。\n\n"
        "第三段 正文内容。"
    )


def test_sanitize_ocrmypdf_text_removes_garbled_lines_and_collapses_cjk_spaces() -> None:
    raw_text = (
        "第一段  正文内容。\n"
        "新兴地主阶级专\n"
        "政，扩大封建制的社会基础。\n"
        "207\n"
        "Be be\n"
        "fis WET GRRE A EL, PMO WES\n"
        "CBR). “PRAT” CK) 。\n"
        "第二段 的 政治、军 事、文 化制度。\n"
        "7}\n"
        "= Il\n"
    )

    assert sanitize_ocrmypdf_text(raw_text) == (
        "第一段 正文内容。\n"
        "新兴地主阶级专政，扩大封建制的社会基础。\n"
        "第二段 的政治、军事、文化制度。"
    )


def test_run_tesseract_pdf_ocr_sanitizes_sidecar_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.reference_utils import run_tesseract_pdf_ocr

    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    source = tmp_path / "external" / "scan.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4 fake")

    sidecar_payload = "附一，中国革命的社会意义 395\n正文内容。\n326\n"

    def fake_run(_command, *, text, capture_output, check):
        ocr_dir = loaded_settings.path_for("ocr_dir")
        (ocr_dir / "scan.ocr.txt").write_text(sidecar_payload, encoding="utf-8")

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("src.reference_utils.shutil.which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr("src.reference_utils.subprocess.run", fake_run)

    text, warnings = run_tesseract_pdf_ocr(source, loaded_settings)

    assert text == "正文内容。"
    assert "ocrmypdf_tesseract" in " ".join(warnings)
