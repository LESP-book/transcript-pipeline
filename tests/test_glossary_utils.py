from __future__ import annotations

from pathlib import Path

from src.glossary_utils import build_initial_prompt, load_glossary_terms, merge_glossary_terms


def test_load_glossary_terms_ignores_blank_lines(tmp_path: Path) -> None:
    glossary = tmp_path / "terms.txt"
    glossary.write_text("马克思\n\n恩格斯\n  \n辩证法\n", encoding="utf-8")

    assert load_glossary_terms(glossary) == ["马克思", "恩格斯", "辩证法"]


def test_merge_glossary_terms_deduplicates_while_preserving_order() -> None:
    merged = merge_glossary_terms(
        ["马克思", "恩格斯"],
        ["恩格斯", "列宁"],
        ["辩证法"],
    )

    assert merged == ["马克思", "恩格斯", "列宁", "辩证法"]


def test_build_initial_prompt_truncates_at_max_chars() -> None:
    prompt = build_initial_prompt(["马克思", "恩格斯", "列宁", "辩证唯物主义"], max_chars=10)

    assert prompt == "马克思，恩格斯，列宁"
