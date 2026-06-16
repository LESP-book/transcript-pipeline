from __future__ import annotations

import re


def normalize_multiline_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = is_blank
    return "\n".join(normalized).strip() + "\n"


def markdown_document_to_plain_text(markdown_text: str) -> str:
    lines: list[str] = []
    in_code_block = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not stripped:
            lines.append("")
            continue
        if not in_code_block:
            line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
            line = re.sub(r"^\s{0,3}>\s?", "", line)
            line = re.sub(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", "", line)
            line = re.sub(r"(?<!\\)([*_`])", "", line)
        lines.append(line.strip())
    return normalize_multiline_text("\n".join(lines))
