from __future__ import annotations

from pathlib import Path


def normalize_term(term: str) -> str:
    return term.strip()


def load_glossary_terms(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [normalized for line in path.read_text(encoding="utf-8").splitlines() if (normalized := normalize_term(line))]


def merge_glossary_terms(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for term in group:
            normalized = normalize_term(term)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def build_initial_prompt(terms: list[str], max_chars: int = 400) -> str:
    if max_chars <= 0:
        return ""

    selected: list[str] = []
    total_length = 0
    for term in terms:
        separator_length = 1 if selected else 0
        projected = total_length + separator_length + len(term)
        if projected > max_chars:
            break
        selected.append(term)
        total_length = projected

    return "，".join(selected)
