from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.refine_utils import (
    BACKEND_CODEX,
    BACKEND_FALLBACK,
    BACKEND_GEMINI,
    BackendDocumentRefinementResult,
    CLIBackendError,
    CLIBackendRetryableError,
    RefinementInputEmptyError,
    build_fallback_document_result,
    build_fulltext_refine_prompt,
    build_refinement_output_path,
    compare_backend_documents,
    load_refinement_prompt,
    parse_backend_document_result,
    refine_batch,
    resolve_refinement_input_paths,
    run_codex_cli,
    run_gemini_cli,
)
from tests.helpers import write_minimal_settings


def write_refine_inputs(tmp_path: Path, *, basename: str = "demo") -> Path:
    asr_dir = tmp_path / "data/intermediate/asr"
    reference_dir = tmp_path / "data/intermediate/extracted_text"
    asr_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    asr_path = asr_dir / f"{basename}.txt"
    asr_path.write_text(
        "九月零云至 崇尚敬江山\n这里 的意思 是 作者在说明情绪变化",
        encoding="utf-8",
    )
    (reference_dir / f"{basename}.txt").write_text(
        "久有凌云志，重上井冈山。\n\n三十八年过去，弹指一挥间。",
        encoding="utf-8",
    )
    return asr_path


def test_refine_batch_raises_when_asr_dir_empty(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    (tmp_path / "data/intermediate/asr").mkdir(parents=True, exist_ok=True)
    loaded_settings = load_settings(project_root=tmp_path)

    with pytest.raises(RefinementInputEmptyError):
        refine_batch(loaded_settings)


def test_resolve_refinement_input_paths_uses_same_basename(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path, basename="same-name")
    loaded_settings = load_settings(project_root=tmp_path)

    paths = resolve_refinement_input_paths(loaded_settings, asr_path)

    assert paths.basename == "same-name"
    assert paths.asr_text_path.name == "same-name.txt"
    assert paths.reference_text_path.name == "same-name.txt"


def test_load_refinement_prompt_reads_prompt_file(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    prompt = load_refinement_prompt(loaded_settings)

    assert prompt == "# test prompt"


def test_build_fulltext_refine_prompt_contains_fulltext_context(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    prompt_text = load_refinement_prompt(loaded_settings)
    input_paths = resolve_refinement_input_paths(loaded_settings, asr_path)

    prompt = build_fulltext_refine_prompt(
        prompt_text,
        input_paths,
        asr_full_text="整篇 ASR 文本",
        reference_full_text="整篇参考原文",
    )

    assert "# test prompt" in prompt
    assert "直接按要求输出最终 Markdown 的 JSON 结果。" in prompt
    assert "录音转写文本：" in prompt
    assert "参考原文：" in prompt
    assert "当前文件: demo.txt" in prompt
    assert "分类摘要" not in prompt
    assert "高置信原文提示" not in prompt
    assert "重点复核块提示" not in prompt


def test_parse_backend_document_result_requires_fulltext() -> None:
    payload = {
        "final_markdown": "# 标题\n\n> 完整精修文本",
        "refinement_strategy": "final_markdown_cleanup",
        "refinement_reason": "test",
        "needs_review_sections": [{"excerpt": "片段", "reason": "test"}],
        "refinement_notes": ["note"],
    }

    result = parse_backend_document_result(BACKEND_GEMINI, payload)

    assert result.backend == BACKEND_GEMINI
    assert result.model_name == ""
    assert result.final_markdown == "# 标题\n\n> 完整精修文本"
    assert result.needs_review_sections[0]["excerpt"] == "片段"
    assert result.refinement_notes == ["note"]


def test_run_gemini_cli_uses_configured_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_minimal_settings(tmp_path, llm_overrides={"gemini_model": "gemini-2.5-flash", "timeout_seconds": 1800})
    loaded_settings = load_settings(project_root=tmp_path)
    seen: dict[str, object] = {}

    def fake_run_subprocess(command: list[str], *, prompt: str, cwd: Path, timeout_seconds: int) -> str:
        seen["command"] = command
        seen["prompt"] = prompt
        seen["cwd"] = cwd
        seen["timeout_seconds"] = timeout_seconds
        return json.dumps(
            {
                "final_markdown": "# 标题\n\n完整精修文本",
                "refinement_strategy": "final_markdown_cleanup",
                "refinement_reason": "ok",
                "needs_review_sections": [],
                "refinement_notes": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("src.refine_utils.run_subprocess", fake_run_subprocess)

    result = run_gemini_cli("prompt", loaded_settings)

    assert "完整精修文本" in result.final_markdown
    assert result.model_name == "gemini-2.5-flash"
    assert seen["command"] == ["gemini", "-m", "gemini-2.5-flash", "-p", "prompt"]
    assert seen["prompt"] == ""
    assert seen["cwd"] == tmp_path
    assert seen["timeout_seconds"] == 1800


def test_run_codex_cli_uses_configured_model_and_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(
        tmp_path,
        llm_overrides={"model": "gpt-5.4", "reasoning_effort": "medium", "timeout_seconds": 1800},
    )
    loaded_settings = load_settings(project_root=tmp_path)
    seen: dict[str, object] = {}

    def fake_run_subprocess(command: list[str], *, prompt: str, cwd: Path, timeout_seconds: int) -> str:
        seen["command"] = command
        seen["prompt"] = prompt
        seen["cwd"] = cwd
        seen["timeout_seconds"] = timeout_seconds
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "final_markdown": "# 标题\n\n完整精修文本",
                    "refinement_strategy": "final_markdown_cleanup",
                    "refinement_reason": "ok",
                    "needs_review_sections": [],
                    "refinement_notes": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ""

    monkeypatch.setattr("src.refine_utils.run_subprocess", fake_run_subprocess)

    result = run_codex_cli("prompt", loaded_settings)
    command = seen["command"]
    assert isinstance(command, list)
    output_index = command.index("-o") + 1

    assert "完整精修文本" in result.final_markdown
    assert result.model_name == "gpt-5.4"
    assert command[:10] == [
        "codex",
        "exec",
        "-C",
        str(tmp_path),
        "-s",
        "read-only",
        "-m",
        "gpt-5.4",
        "-c",
        'model_reasoning_effort="medium"',
    ]
    assert command[output_index - 1] == "-o"
    assert command[-1] == "-"
    assert seen["prompt"] == "prompt"
    assert seen["cwd"] == tmp_path
    assert seen["timeout_seconds"] == 1800


def test_run_gemini_cli_retries_with_fallback_model_on_capacity_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(
        tmp_path,
        llm_overrides={
            "gemini_model": "gemini-3.1-pro-preview",
            "gemini_fallback_model": "gemini-3-flash",
            "timeout_seconds": 1800,
        },
    )
    loaded_settings = load_settings(project_root=tmp_path)
    seen_commands: list[list[str]] = []

    def fake_run_subprocess(command: list[str], *, prompt: str, cwd: Path, timeout_seconds: int) -> str:
        seen_commands.append(command)
        if command[2] == "gemini-3.1-pro-preview":
            raise CLIBackendRetryableError(
                "CLI 命令执行失败: gemini -m gemini-3.1-pro-preview -p prompt | 429 MODEL_CAPACITY_EXHAUSTED"
            )
        return json.dumps(
            {
                "final_markdown": "# 标题\n\n备用模型结果",
                "refinement_strategy": "final_markdown_cleanup",
                "refinement_reason": "fallback_model",
                "needs_review_sections": [],
                "refinement_notes": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("src.refine_utils.run_subprocess", fake_run_subprocess)

    result = run_gemini_cli("prompt", loaded_settings)

    assert result.final_markdown == "# 标题\n\n备用模型结果"
    assert result.model_name == "gemini-3-flash"
    assert seen_commands == [
        ["gemini", "-m", "gemini-3.1-pro-preview", "-p", "prompt"],
        ["gemini", "-m", "gemini-3-flash", "-p", "prompt"],
    ]


def test_compare_backend_documents_prefers_reference_closer_result_for_quote_heavy() -> None:
    codex_result = BackendDocumentRefinementResult(
        backend=BACKEND_CODEX,
        model_name="codex_default",
        final_markdown="# 文稿\n\n> 久有凌云志，重上井冈山。\n\n> 风雷动，旌旗奋，是人寰。",
        refinement_strategy="final_markdown_reference_restore",
        refinement_reason="codex",
        needs_review_sections=[],
        refinement_notes=[],
    )
    gemini_result = BackendDocumentRefinementResult(
        backend=BACKEND_GEMINI,
        model_name="gemini-3.1-pro-preview",
        final_markdown="# 文稿\n\n九月零云至 崇尚敬江山。\n\n兵起奋是人还 三十八年过去。",
        refinement_strategy="final_markdown_cleanup",
        refinement_reason="gemini",
        needs_review_sections=[{"excerpt": "兵起奋是人还", "reason": "uncertain"}],
        refinement_notes=[],
    )

    selected, summary = compare_backend_documents(
        asr_full_text="九月零云至 崇尚敬江山\n兵起奋是人还 三十八年过去",
        reference_full_text="久有凌云志，重上井冈山。\n\n风雷动，旌旗奋，是人寰。",
        candidates=[codex_result, gemini_result],
    )

    assert selected.backend == BACKEND_CODEX
    assert "selected=codex_cli" in summary


def test_build_fallback_document_result_uses_full_asr_text() -> None:
    result = build_fallback_document_result("demo", "九月零云至 崇尚敬江山\n\n这里 的意思 是 作者在说明情绪变化")

    assert result.backend == BACKEND_FALLBACK
    assert result.model_name == BACKEND_FALLBACK
    assert "# demo" in result.final_markdown
    assert "九月零云至 崇尚敬江山" in result.final_markdown
    assert result.refinement_notes == ["all_cli_backends_failed_use_fallback"]
    assert len(result.needs_review_sections) == 2


def test_refine_batch_writes_expected_fulltext_output_structure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    def fake_run_backend_cli(backend: str, _prompt: str, _loaded_settings) -> BackendDocumentRefinementResult:
        if backend == BACKEND_CODEX:
            return BackendDocumentRefinementResult(
                backend=BACKEND_CODEX,
                model_name="codex_default",
                final_markdown="# demo\n\n> 久有凌云志，重上井冈山。\n\n这里的意思是作者在说明情绪变化。",
                refinement_strategy="final_markdown_cleanup",
                refinement_reason="codex_fulltext",
                needs_review_sections=[],
                refinement_notes=["codex_note"],
            )
        return BackendDocumentRefinementResult(
            backend=BACKEND_GEMINI,
            model_name="gemini-3.1-pro-preview",
            final_markdown="# demo\n\n久有凌云志重上井冈山\n\n这里的意思是作者在说明情绪变化",
            refinement_strategy="final_markdown_cleanup",
            refinement_reason="gemini_fulltext",
            needs_review_sections=[{"excerpt": "久有凌云志重上井冈山", "reason": "punctuation"}],
            refinement_notes=["gemini_note"],
        )

    monkeypatch.setattr("src.refine_utils.run_backend_cli", fake_run_backend_cli)

    summary = refine_batch(loaded_settings)
    output_path = build_refinement_output_path(asr_path, tmp_path / "data/intermediate/refined")
    result = json.loads(output_path.json_path.read_text(encoding="utf-8"))

    assert summary.success == 1
    assert result["prompt_mode"] == "fulltext_final_markdown"
    assert result["source_asr_file"] == "data/intermediate/asr/demo.txt"
    assert result["source_reference_file"] == "data/intermediate/extracted_text/demo.txt"
    assert result["refinement_backends"] == [BACKEND_CODEX]
    assert result["backend_status"]["codex_cli"] == "returned_fulltext:model=codex_default"
    assert result["selected_backend"] == BACKEND_CODEX
    assert "final_markdown" in result
    assert result["final_markdown"].startswith("# demo")
    assert "classification_summary" not in result


def test_refine_batch_uses_fallback_when_all_backends_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    def fail_backend(_backend: str, _prompt: str, _loaded_settings) -> BackendDocumentRefinementResult:
        raise CLIBackendError("backend failed")

    monkeypatch.setattr("src.refine_utils.run_backend_cli", fail_backend)

    summary = refine_batch(loaded_settings)
    output_path = build_refinement_output_path(asr_path, tmp_path / "data/intermediate/refined")
    result = json.loads(output_path.json_path.read_text(encoding="utf-8"))

    assert summary.success == 1
    assert result["refinement_backends"] == [BACKEND_CODEX]
    assert result["backend_status"]["codex_cli"] == "failed_on_file"
    assert "gemini_cli" not in result["backend_status"]
    assert result["backend_status"]["fallback"] == "used"
    assert result["selected_backend"] == BACKEND_FALLBACK
