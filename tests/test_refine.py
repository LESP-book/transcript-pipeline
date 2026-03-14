from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.config_loader import load_settings
from src.refine_utils import (
    BACKEND_CODEX,
    BACKEND_FALLBACK,
    BACKEND_GEMINI,
    BackendDocumentRefinementResult,
    PreReplacementSegment,
    CLIBackendError,
    CLIBackendRetryableError,
    RefinementBlock,
    RefinementInputEmptyError,
    build_pre_replaced_document,
    build_fallback_document_result,
    build_markdown_assemble_prompt,
    build_minimal_edit_prompt,
    build_refinement_blocks,
    build_single_pass_refine_prompt,
    build_fulltext_refine_prompt,
    build_refinement_output_path,
    compare_backend_documents,
    load_refinement_prompt,
    parse_backend_document_result,
    refine_batch,
    resolve_refinement_input_paths,
    run_codex_cli,
    run_gemini_cli,
    validate_minimal_edit_result,
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


def test_build_refinement_blocks_includes_adjacent_context() -> None:
    blocks = build_refinement_blocks(
        "第一段。\n\n第二段。\n\n第三段。",
        chunk_paragraphs=1,
        anchor_paragraphs=1,
    )

    assert len(blocks) == 3
    assert blocks[1] == RefinementBlock(
        index=1,
        current_text="第二段。",
        previous_anchor="第一段。",
        next_anchor="第三段。",
    )


def test_build_refinement_blocks_scales_down_long_line_based_asr_to_about_twenty_calls() -> None:
    line_based_text = "\n".join(f"第{i:04d}行转写文本" for i in range(200))

    blocks = build_refinement_blocks(
        line_based_text,
        chunk_paragraphs=2,
        anchor_paragraphs=1,
    )

    assert len(blocks) == 20
    assert blocks[0].current_text.count("\n\n") == 9
    assert blocks[-1].current_text.count("\n\n") == 9


def test_build_minimal_edit_prompt_contains_context_and_hard_guards(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    prompt_text = load_refinement_prompt(loaded_settings)
    input_paths = resolve_refinement_input_paths(loaded_settings, asr_path)

    prompt = build_minimal_edit_prompt(
        prompt_text,
        input_paths,
        RefinementBlock(
            index=0,
            current_text="久有零云志 重上敬岗山",
            previous_anchor="前文锚点",
            next_anchor="后文锚点",
        ),
        reference_full_text="久有凌云志，重上井冈山。",
    )

    assert "你现在只允许编辑“当前块”文本" in prompt
    assert "当前块正文" in prompt
    assert "前文锚点" in prompt
    assert "后文锚点" in prompt
    assert "绝对禁止" in prompt
    assert "不得总结压缩" in prompt
    assert "删除噪音必须记录" in prompt
    assert "参考原文" in prompt


def test_validate_minimal_edit_result_rejects_summary_style_compression() -> None:
    report = validate_minimal_edit_result(
        source_text="这个地方他其实不是单纯抒情，而是说革命在低潮以后重新起来，所以情绪往上走。",
        edited_text="这里主要是表达革命重新高涨。",
        deletion_candidates=[],
    )

    assert report["passed"] is False
    assert "summary_phrase_detected" in report["reasons"]
    assert "length_ratio_too_low" in report["reasons"]


def test_build_markdown_assemble_prompt_restricts_to_structure_only(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    input_paths = resolve_refinement_input_paths(loaded_settings, asr_path)

    prompt = build_markdown_assemble_prompt(
        "# test final cleanup",
        input_paths,
        edited_plain_text="久有凌云志，重上井冈山。\n\n这里的意思是作者在说明情绪变化。",
        reference_full_text="久有凌云志，重上井冈山。",
    )

    assert "只负责 Markdown 结构整理" in prompt
    assert "不得改写 edited_plain_text 的措辞" in prompt
    assert "edited_plain_text" in prompt
    assert "参考原文" in prompt


def test_build_pre_replaced_document_locks_only_high_confidence_reference_runs(tmp_path: Path) -> None:
    write_minimal_settings(
        tmp_path,
        llm_overrides={
            "safe_replace_min_score": 80,
            "safe_replace_min_margin": 5,
            "safe_replace_length_ratio_min": 0.8,
            "safe_replace_length_ratio_max": 1.2,
            "safe_replace_max_extra_content_ratio": 0.12,
            "safe_replace_min_run_length": 2,
        },
    )
    loaded_settings = load_settings(project_root=tmp_path)

    segments = build_pre_replaced_document(
        asr_full_text="天地玄黄 宇宙洪荒。\n\n日月盈昃 辰宿列张。\n\n这里是在解释宇宙观。",
        reference_full_text="天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。",
        loaded_settings=loaded_settings,
    )

    assert segments == [
        PreReplacementSegment(
            segment_type="locked_quote",
            text="天地玄黄，宇宙洪荒。\n\n日月盈昃，辰宿列张。",
            source_text="天地玄黄 宇宙洪荒。\n\n日月盈昃 辰宿列张。",
            reference_text="天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。",
            start_sentence_index=0,
            end_sentence_index=1,
        ),
        PreReplacementSegment(
            segment_type="unlocked_text",
            text="这里是在解释宇宙观。",
            source_text="这里是在解释宇宙观。",
            reference_text="",
            start_sentence_index=2,
            end_sentence_index=2,
        ),
    ]


def test_build_pre_replaced_document_does_not_lock_sentence_followed_by_explanation(tmp_path: Path) -> None:
    write_minimal_settings(
        tmp_path,
        llm_overrides={
            "safe_replace_min_score": 80,
            "safe_replace_min_margin": 5,
            "safe_replace_length_ratio_min": 0.8,
            "safe_replace_length_ratio_max": 1.2,
            "safe_replace_max_extra_content_ratio": 0.12,
            "safe_replace_min_run_length": 2,
        },
    )
    loaded_settings = load_settings(project_root=tmp_path)

    segments = build_pre_replaced_document(
        asr_full_text="天地玄黄 宇宙洪荒。\n\n这里是在解释为什么先讲宇宙。",
        reference_full_text="天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。",
        loaded_settings=loaded_settings,
    )

    assert segments == [
        PreReplacementSegment(
            segment_type="unlocked_text",
            text="天地玄黄 宇宙洪荒。\n\n这里是在解释为什么先讲宇宙。",
            source_text="天地玄黄 宇宙洪荒。\n\n这里是在解释为什么先讲宇宙。",
            reference_text="",
            start_sentence_index=0,
            end_sentence_index=1,
        )
    ]


def test_build_single_pass_refine_prompt_includes_reference_and_locking_rules(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)
    input_paths = resolve_refinement_input_paths(loaded_settings, asr_path)

    prompt = build_single_pass_refine_prompt(
        "# test final cleanup",
        input_paths,
        pre_replaced_segments=[
            PreReplacementSegment(
                segment_type="locked_quote",
                text="天地玄黄，宇宙洪荒。",
                source_text="天地玄黄 宇宙洪荒。",
                reference_text="天地玄黄，宇宙洪荒。",
                start_sentence_index=0,
                end_sentence_index=0,
            ),
            PreReplacementSegment(
                segment_type="unlocked_text",
                text="这里是在解释宇宙观。",
                source_text="这里是在解释宇宙观。",
                reference_text="",
                start_sentence_index=1,
                end_sentence_index=1,
            ),
        ],
        reference_full_text="天地玄黄，宇宙洪荒。",
    )

    assert "预替换全文" in prompt
    assert "整篇参考原文" in prompt
    assert "[SEGMENT 01][locked_quote]" in prompt
    assert "[SEGMENT 02][unlocked_text]" in prompt
    assert "不得改写 locked_quote 的实词内容" in prompt
    assert "仅允许在 unlocked_text 中结合参考原文继续修正" in prompt


def test_refine_batch_uses_single_codex_call_with_reference_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(
        tmp_path,
        llm_overrides={
            "block_batch_size": 1,
            "safe_replace_min_score": 80,
            "safe_replace_min_margin": 5,
            "safe_replace_length_ratio_min": 0.8,
            "safe_replace_length_ratio_max": 1.2,
            "safe_replace_max_extra_content_ratio": 0.12,
            "safe_replace_min_run_length": 2,
        },
    )
    asr_dir = tmp_path / "data/intermediate/asr"
    reference_dir = tmp_path / "data/intermediate/extracted_text"
    asr_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    (asr_dir / "single-pass-demo.txt").write_text(
        "天地玄黄 宇宙洪荒。\n\n日月盈昃 辰宿列张。\n\n这里是在解释宇宙观。",
        encoding="utf-8",
    )
    (reference_dir / "single-pass-demo.txt").write_text(
        "天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。",
        encoding="utf-8",
    )
    loaded_settings = load_settings(project_root=tmp_path)

    prompts: list[str] = []

    def fake_run_codex_payload(prompt: str, _loaded_settings) -> dict[str, object]:
        prompts.append(prompt)
        if "当前块正文" in prompt:
            current_text = prompt.split("当前块正文：\n", 1)[1].split("\n\n后文锚点：", 1)[0].strip()
            return {
                "edited_text": current_text,
                "deletion_candidates": [],
                "edit_notes": [],
                "needs_review_sections": [],
            }

        return {
            "final_markdown": "# single-pass-demo\n\n> 天地玄黄，宇宙洪荒。\n>\n> 日月盈昃，辰宿列张。\n\n这里是在解释宇宙观。",
            "section_map": [],
            "refinement_notes": [],
            "needs_review_sections": [],
            "refinement_strategy": "single_pass_with_safe_replace",
            "refinement_reason": "single_pass_codex",
        }

    monkeypatch.setattr("src.refine_utils.run_codex_cli_payload", fake_run_codex_payload)

    refine_batch(loaded_settings)

    assert len(prompts) == 1
    assert "整篇参考原文" in prompts[0]
    assert "[SEGMENT 01][locked_quote]" in prompts[0]
    assert "[SEGMENT 02][unlocked_text]" in prompts[0]


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
    write_minimal_settings(tmp_path, llm_overrides={"block_batch_size": 1})
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    def fake_run_codex_payload(prompt: str, _loaded_settings) -> dict[str, object]:
        return {
            "final_markdown": "# demo\n\n> 久有凌云志，重上井冈山。\n\n这里 的意思 是 作者在说明情绪变化。",
            "section_map": [{"section": "quote", "source_blocks": [0]}],
            "refinement_notes": ["codex_note"],
            "needs_review_sections": [],
            "refinement_strategy": "single_pass_with_safe_replace",
            "refinement_reason": "single_pass_codex",
        }

    monkeypatch.setattr("src.refine_utils.run_codex_cli_payload", fake_run_codex_payload)

    summary = refine_batch(loaded_settings)
    output_path = build_refinement_output_path(asr_path, tmp_path / "data/intermediate/refined")
    result = json.loads(output_path.json_path.read_text(encoding="utf-8"))

    assert summary.success == 1
    assert result["prompt_mode"] == "single_pass_safe_replace"
    assert result["source_asr_file"] == "data/intermediate/asr/demo.txt"
    assert result["source_reference_file"] == "data/intermediate/extracted_text/demo.txt"
    assert result["refinement_backends"] == [BACKEND_CODEX]
    assert result["backend_status"]["codex_cli"] == "returned_single_pass:model=codex_cli"
    assert result["selected_backend"] == BACKEND_CODEX
    assert "final_markdown" in result
    assert result["final_markdown"].startswith("# demo")
    assert result["edited_plain_text"].startswith("九月零云至 崇尚敬江山")
    assert "这里 的意思 是 作者在说明情绪变化" in result["edited_plain_text"]
    assert result["deletion_candidates"] == []
    assert result["fidelity_report"]["passed"] is True
    assert result["refinement_notes"] == ["codex_note"]
    assert "classification_summary" not in result


def test_refine_batch_uses_single_codex_call_for_long_line_based_asr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, llm_overrides={"block_batch_size": 2, "block_concurrency": 6})
    asr_dir = tmp_path / "data/intermediate/asr"
    reference_dir = tmp_path / "data/intermediate/extracted_text"
    asr_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    asr_path = asr_dir / "long-demo.txt"
    line_count = 200
    asr_path.write_text("\n".join(f"第{i:04d}行转写文本" for i in range(line_count)), encoding="utf-8")
    (reference_dir / "long-demo.txt").write_text("参考原文", encoding="utf-8")
    loaded_settings = load_settings(project_root=tmp_path)

    prompts: list[str] = []

    def fake_run_codex_payload(prompt: str, _loaded_settings) -> dict[str, object]:
        prompts.append(prompt)
        return {
            "final_markdown": "# long-demo\n\n" + "\n\n".join(f"第{i:04d}行转写文本" for i in range(line_count)),
            "section_map": [],
            "refinement_notes": [],
            "needs_review_sections": [],
            "refinement_strategy": "single_pass_with_safe_replace",
            "refinement_reason": "single_pass_codex",
        }

    monkeypatch.setattr("src.refine_utils.run_codex_cli_payload", fake_run_codex_payload)

    refine_batch(loaded_settings)

    assert len(prompts) == 1
    assert "整篇参考原文" in prompts[0]
    assert "预替换全文" in prompts[0]


def test_refine_batch_does_not_use_block_concurrency_in_single_pass_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path, llm_overrides={"block_batch_size": 1, "block_concurrency": 6})
    asr_dir = tmp_path / "data/intermediate/asr"
    reference_dir = tmp_path / "data/intermediate/extracted_text"
    asr_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    (asr_dir / "parallel-demo.txt").write_text("\n".join(f"第{i:04d}行转写文本" for i in range(12)), encoding="utf-8")
    (reference_dir / "parallel-demo.txt").write_text("参考原文", encoding="utf-8")
    loaded_settings = load_settings(project_root=tmp_path)

    seen: dict[str, object] = {}

    class FakeExecutor:
        def __init__(self, *, max_workers: int) -> None:
            seen["max_workers"] = max_workers

        def __enter__(self) -> "FakeExecutor":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            _ = exc_type, exc, tb

    def fake_run_codex_payload(prompt: str, _loaded_settings) -> dict[str, object]:
        return {
            "final_markdown": "# parallel-demo\n\n正文",
            "section_map": [],
            "refinement_notes": [],
            "needs_review_sections": [],
            "refinement_strategy": "single_pass_with_safe_replace",
            "refinement_reason": "single_pass_codex",
        }

    monkeypatch.setattr("src.refine_utils.ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr("src.refine_utils.run_codex_cli_payload", fake_run_codex_payload)

    refine_batch(loaded_settings)

    assert "max_workers" not in seen


def test_refine_batch_logs_single_pass_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    write_minimal_settings(tmp_path, llm_overrides={"block_batch_size": 2, "block_concurrency": 6})
    asr_dir = tmp_path / "data/intermediate/asr"
    reference_dir = tmp_path / "data/intermediate/extracted_text"
    asr_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    (asr_dir / "progress-demo.txt").write_text("\n".join(f"第{i:04d}行转写文本" for i in range(30)), encoding="utf-8")
    (reference_dir / "progress-demo.txt").write_text("参考原文", encoding="utf-8")
    loaded_settings = load_settings(project_root=tmp_path)

    def fake_run_codex_payload(prompt: str, _loaded_settings) -> dict[str, object]:
        return {
            "final_markdown": "# progress-demo\n\n正文",
            "section_map": [],
            "refinement_notes": [],
            "needs_review_sections": [],
            "refinement_strategy": "single_pass_with_safe_replace",
            "refinement_reason": "single_pass_codex",
        }

    monkeypatch.setattr("src.refine_utils.run_codex_cli_payload", fake_run_codex_payload)

    with caplog.at_level("INFO"):
        refine_batch(loaded_settings, logger=logging.getLogger("test-refine-progress"))

    progress_messages = [record.message for record in caplog.records if "阶段 6 单次调用" in record.message]
    assert len(progress_messages) == 1
    assert "file=progress-demo" in progress_messages[0]
    assert "backend=codex_cli" in progress_messages[0]
    assert "locked_segments=" in progress_messages[0]
    assert "total_segments=" in progress_messages[0]


def test_refine_batch_uses_fallback_when_all_backends_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_settings(tmp_path)
    asr_path = write_refine_inputs(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    def fail_backend(**_kwargs) -> BackendDocumentRefinementResult:
        raise CLIBackendError("backend failed")

    monkeypatch.setattr("src.refine_utils.run_single_pass_backend_refinement", fail_backend)

    summary = refine_batch(loaded_settings)
    output_path = build_refinement_output_path(asr_path, tmp_path / "data/intermediate/refined")
    result = json.loads(output_path.json_path.read_text(encoding="utf-8"))

    assert summary.success == 1
    assert result["refinement_backends"] == [BACKEND_CODEX]
    assert result["backend_status"]["codex_cli"] == "failed_on_file"
    assert "gemini_cli" not in result["backend_status"]
    assert result["backend_status"]["fallback"] == "used"
    assert result["selected_backend"] == BACKEND_FALLBACK
