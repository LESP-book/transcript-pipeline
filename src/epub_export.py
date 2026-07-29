from __future__ import annotations

import hashlib
import html
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal

from src.runtime_utils import ensure_directory


class EpubExportError(RuntimeError):
    """EPUB 导出失败。"""


@dataclass(frozen=True)
class EpubWarning:
    """一个可追踪但不阻断导出的解析警告。"""

    kind: str
    message: str
    source_position: int | None = None
    label: str | None = None

    def format(self) -> str:
        position = "" if self.source_position is None else f"位置={self.source_position} | "
        label = "" if self.label is None else f"标记={self.label} | "
        return f"{self.kind} | {position}{label}{self.message}"


@dataclass(frozen=True)
class EpubNote:
    """从源文本中可靠拆出的脚注或尾注定义。"""

    note_id: str
    kind: Literal["footnote", "endnote"]
    label: str
    body: str
    scope_id: str
    source_start: int
    source_end: int


@dataclass(frozen=True)
class EpubReference:
    """正文中的脚注/尾注引用。"""

    reference_id: str
    kind: Literal["footnote", "endnote"]
    label: str
    source_start: int
    source_end: int
    target_note_id: str | None


@dataclass(frozen=True)
class EpubBodyBlock:
    """一个保留源位置的正文或标题块。"""

    block_id: str
    text: str
    source_start: int
    source_end: int
    line_index: int
    scope_id: str
    heading_level: int | None


@dataclass(frozen=True)
class EpubBookDocument:
    """EPUB 导出使用的内存语义模型。"""

    title: str
    author: str | None
    language: str
    body_blocks: tuple[EpubBodyBlock, ...]
    footnotes: tuple[EpubNote, ...]
    endnotes: tuple[EpubNote, ...]
    references: tuple[EpubReference, ...]
    warnings: tuple[EpubWarning, ...]


@dataclass(frozen=True)
class EpubExportResult:
    """EPUB 文件输出结果。"""

    output_path: Path
    document: EpubBookDocument


@dataclass(frozen=True)
class _TextLine:
    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _NumericDefinition:
    label: str
    definition_start: int
    body_start: int
    line_index: int


@dataclass(frozen=True)
class _TailRegion:
    start: int
    definitions: tuple[_NumericDefinition, ...]


_CIRCLE_CHARS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟"
_CIRCLE_RE = re.compile(f"[{re.escape(_CIRCLE_CHARS)}]")
_CIRCLE_DEFINITION_RE = re.compile(
    rf"^\s*(?P<label>[{re.escape(_CIRCLE_CHARS)}])"
    r"(?P<separator>\s+|[、.．:：)\]）])(?P<body>.*)$"
)
_NUMERIC_DEFINITION_RE = re.compile(
    r"^\s*(?P<label>\d+)(?P<separator>\s+|[.．、:：)\]）-])(?P<body>.*)$"
)
_NOTE_HEADING_RE = re.compile(r"^\s*(?:注释|尾注|附注|编者注|译者注|书后注|本书注释)\s*[:：]?\s*$")
_NOTE_END_RE = re.compile(
    r"(?:——(?:编者|译者|作者)注|"
    r"[（(][^（）()]*?(?:加的注|注)[^（）()]*[）)])"
)
_SECTION_HEADING_RE = re.compile(r"^\s*[一二三四五六七八九十百千万]+、")
_CHAPTER_HEADING_RE = re.compile(r"^\s*第[一二三四五六七八九十百千万\d]+[章节篇部卷]")
_LETTER_HEADING_RE = re.compile(r"^\s*[（(][甲乙丙丁戊己庚辛壬癸][）)]")
_NAMED_HEADING_RE = re.compile(r"(?:序言|出版说明|前言|导言|引言|后记|附录)\d*$")
_DATE_UNITS = frozenset("年月日时分秒版卷期页章节回")
_CLOSING_CONTEXT = frozenset("》”’）)]】〉》")


def _line_spans(text: str) -> list[_TextLine]:
    lines: list[_TextLine] = []
    cursor = 0
    for index, raw_line in enumerate(text.splitlines(keepends=True)):
        content = raw_line.rstrip("\r\n")
        content_end = cursor + len(content)
        lines.append(_TextLine(index=index, start=cursor, end=content_end, text=content))
        cursor += len(raw_line)
    if cursor < len(text):
        lines.append(_TextLine(index=len(lines), start=cursor, end=len(text), text=text[cursor:]))
    return lines


def _normalize_source_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _normalize_note_body(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _apply_masks(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    chars = list(text)
    for start, end in sorted(spans):
        for index in range(start, end):
            if chars[index] not in "\r\n":
                chars[index] = " "
    return "".join(chars)


def _heading_level(text: str) -> int | None:
    stripped = text.strip()
    if not stripped:
        return None
    if _SECTION_HEADING_RE.match(stripped) or _CHAPTER_HEADING_RE.match(stripped):
        return 2
    if _LETTER_HEADING_RE.match(stripped):
        return 3
    if _NAMED_HEADING_RE.search(stripped):
        return 2
    return None


def _scope_ids(lines: list[_TextLine]) -> list[str]:
    scopes: list[str] = []
    current_scope = "scope-root"
    for line in lines:
        if _heading_level(line.text) is not None:
            current_scope = f"scope-line-{line.index}"
        scopes.append(current_scope)
    return scopes


def _numeric_definitions(lines: list[_TextLine]) -> list[_NumericDefinition]:
    definitions: list[_NumericDefinition] = []
    for line in lines:
        match = _NUMERIC_DEFINITION_RE.match(line.text)
        if match is None:
            continue
        body_start = line.start + match.start("body")
        definitions.append(
            _NumericDefinition(
                label=match.group("label"),
                definition_start=line.start + match.start(),
                body_start=body_start,
                line_index=line.index,
            )
        )
    return definitions


def _previous_non_space(text: str, index: int) -> str:
    while index >= 0 and text[index].isspace():
        index -= 1
    return text[index] if index >= 0 else ""


def _next_non_space(text: str, index: int) -> str:
    while index < len(text) and text[index].isspace():
        index += 1
    return text[index] if index < len(text) else ""


def _looks_like_numeric_reference(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    previous_non_space = _previous_non_space(text, start - 1)
    next_non_space = _next_non_space(text, end)

    if before.isdigit() or after.isdigit():
        return False
    if next_non_space in _DATE_UNITS:
        return False
    if previous_non_space == "第" and next_non_space in _DATE_UNITS:
        return False
    if after in "—-–/" or before in "—-–/":
        return False
    if before in ".．" or after in ".．":
        return False
    if not before:
        return False
    if before.isspace() and previous_non_space not in _CLOSING_CONTEXT and not ("\u4e00" <= previous_non_space <= "\u9fff"):
        return False
    if not before.isspace() and before not in _CLOSING_CONTEXT and not ("\u4e00" <= before <= "\u9fff"):
        return False
    return True


def _has_numeric_reference(text: str, labels: set[str]) -> bool:
    for match in re.finditer(r"\d+", text):
        if match.group() in labels and _looks_like_numeric_reference(text, match.start(), match.end()):
            return True
    return False


def _find_tail_region(text: str, lines: list[_TextLine]) -> _TailRegion | None:
    definitions = _numeric_definitions(lines)
    if not definitions:
        return None

    explicit_candidates = [
        line
        for line in lines
        if _NOTE_HEADING_RE.fullmatch(line.text)
    ]
    for heading in reversed(explicit_candidates):
        after_heading = tuple(definition for definition in definitions if definition.line_index > heading.index)
        if after_heading:
            return _TailRegion(start=heading.start, definitions=after_heading)

    if len(definitions) < 2:
        return None

    run_start = len(definitions) - 1
    while run_start > 0:
        previous = definitions[run_start - 1]
        current = definitions[run_start]
        if int(previous.label) + 1 != int(current.label):
            break
        run_start -= 1

    candidate_definitions = tuple(definitions[run_start:])
    if len(candidate_definitions) < 2:
        return None
    labels = {definition.label for definition in candidate_definitions}
    prefix = text[:candidate_definitions[0].definition_start]
    if not _has_numeric_reference(prefix, labels):
        return None
    return _TailRegion(
        start=candidate_definitions[0].definition_start,
        definitions=candidate_definitions,
    )


def _extract_endnotes(
    text: str,
    lines: list[_TextLine],
) -> tuple[list[EpubNote], list[tuple[int, int]], list[EpubWarning]]:
    tail_region = _find_tail_region(text, lines)
    if tail_region is None:
        return [], [], []

    notes: list[EpubNote] = []
    warnings: list[EpubWarning] = []
    label_counts: dict[str, int] = {}
    for index, definition in enumerate(tail_region.definitions, start=1):
        next_start = (
            tail_region.definitions[index].definition_start
            if index < len(tail_region.definitions)
            else len(text)
        )
        body = _normalize_note_body(text[definition.body_start:next_start])
        label_counts[definition.label] = label_counts.get(definition.label, 0) + 1
        note_id = f"en-{definition.label}-{label_counts[definition.label]}"
        if not body:
            warnings.append(
                EpubWarning(
                    kind="empty-endnote-definition",
                    label=definition.label,
                    source_position=definition.definition_start,
                    message="尾注定义没有识别到正文，仍保留该定义以便人工检查。",
                )
            )
        notes.append(
            EpubNote(
                note_id=note_id,
                kind="endnote",
                label=definition.label,
                body=body,
                scope_id="scope-book",
                source_start=definition.definition_start,
                source_end=next_start,
            )
        )
    return notes, [(tail_region.start, len(text))], warnings


def _extract_footnotes(
    text: str,
    lines: list[_TextLine],
) -> tuple[list[EpubNote], list[tuple[int, int]], list[EpubWarning]]:
    scopes = _scope_ids(lines)
    candidates: list[tuple[_TextLine, re.Match[str]]] = []
    for line in lines:
        match = _CIRCLE_DEFINITION_RE.match(line.text)
        if match is not None:
            candidates.append((line, match))

    notes: list[EpubNote] = []
    masks: list[tuple[int, int]] = []
    warnings: list[EpubWarning] = []
    note_sequence = 0
    next_unprocessed_position = -1
    for candidate_index, (line, match) in enumerate(candidates):
        marker_start = line.start + match.start()
        if marker_start < next_unprocessed_position:
            continue
        boundary = (
            candidates[candidate_index + 1][0].start
            if candidate_index + 1 < len(candidates)
            else len(text)
        )
        segment = text[marker_start:boundary]
        end_match = _NOTE_END_RE.search(segment)
        if end_match is None:
            warnings.append(
                EpubWarning(
                    kind="uncertain-footnote-end",
                    label=match.group("label"),
                    source_position=marker_start,
                    message="圆圈数字定义没有可靠的语义结束位置，保留在正文中。",
                )
            )
            continue

        note_end = marker_start + end_match.end()
        body_start = line.start + match.start("body")
        body = _normalize_note_body(text[body_start:note_end])
        note_sequence += 1
        note_id = f"fn-{note_sequence:04d}"
        notes.append(
            EpubNote(
                note_id=note_id,
                kind="footnote",
                label=match.group("label"),
                body=body,
                scope_id=scopes[line.index] if line.index < len(scopes) else "scope-root",
                source_start=marker_start,
                source_end=note_end,
            )
        )
        masks.append((marker_start, note_end))
        next_unprocessed_position = note_end
    return notes, masks, warnings


def _build_body_blocks(text: str, lines: list[_TextLine]) -> tuple[EpubBodyBlock, ...]:
    scopes = _scope_ids(lines)
    blocks: list[EpubBodyBlock] = []
    for line in lines:
        line_text = text[line.start:line.end]
        stripped = line_text.strip()
        if not stripped:
            continue
        leading_spaces = len(line_text) - len(line_text.lstrip())
        block_start = line.start + leading_spaces
        block_text = line_text.lstrip().rstrip()
        block_end = block_start + len(block_text)
        blocks.append(
            EpubBodyBlock(
                block_id=f"p-{len(blocks) + 1:06d}",
                text=block_text,
                source_start=block_start,
                source_end=block_end,
                line_index=line.index,
                scope_id=scopes[line.index] if line.index < len(scopes) else "scope-root",
                heading_level=_heading_level(block_text),
            )
        )
    return tuple(blocks)


def _resolve_footnote_reference(
    label: str,
    scope_id: str,
    footnotes_by_label: dict[str, list[EpubNote]],
) -> tuple[EpubNote | None, str | None]:
    candidates = footnotes_by_label.get(label, [])
    scoped = [note for note in candidates if note.scope_id == scope_id]
    if len(scoped) == 1:
        return scoped[0], None
    if len(scoped) > 1:
        return None, "同一局部范围内存在多个相同圆圈数字定义"
    if len(candidates) == 1:
        return candidates[0], None
    if candidates:
        return None, "相同圆圈数字在多个局部范围出现，无法可靠消歧"
    return None, "没有找到对应的圆圈数字定义"


def _collect_references(
    blocks: tuple[EpubBodyBlock, ...],
    footnotes: tuple[EpubNote, ...],
    endnotes: tuple[EpubNote, ...],
) -> tuple[list[EpubReference], list[EpubWarning]]:
    footnotes_by_label: dict[str, list[EpubNote]] = {}
    for note in footnotes:
        footnotes_by_label.setdefault(note.label, []).append(note)
    endnotes_by_label: dict[str, list[EpubNote]] = {}
    for note in endnotes:
        endnotes_by_label.setdefault(note.label, []).append(note)

    references: list[EpubReference] = []
    warnings: list[EpubWarning] = []
    reference_sequence = 0
    for block in blocks:
        for match in _CIRCLE_RE.finditer(block.text):
            if not block.text[:match.start()].strip():
                continue
            label = match.group()
            target, reason = _resolve_footnote_reference(label, block.scope_id, footnotes_by_label)
            reference_sequence += 1
            reference_id = f"ref-{reference_sequence:04d}"
            references.append(
                EpubReference(
                    reference_id=reference_id,
                    kind="footnote",
                    label=label,
                    source_start=block.source_start + match.start(),
                    source_end=block.source_start + match.end(),
                    target_note_id=target.note_id if target else None,
                )
            )
            if reason:
                warnings.append(
                    EpubWarning(
                        kind="unmatched-footnote-reference",
                        label=label,
                        source_position=block.source_start + match.start(),
                        message=reason,
                    )
                )

        for match in re.finditer(r"\d+", block.text):
            if not _looks_like_numeric_reference(block.text, match.start(), match.end()):
                continue
            label = match.group()
            if label not in endnotes_by_label:
                reference_sequence += 1
                reference_id = f"ref-{reference_sequence:04d}"
                references.append(
                    EpubReference(
                        reference_id=reference_id,
                        kind="endnote",
                        label=label,
                        source_start=block.source_start + match.start(),
                        source_end=block.source_start + match.end(),
                        target_note_id=None,
                    )
                )
                warnings.append(
                    EpubWarning(
                        kind="unmatched-endnote-reference",
                        label=label,
                        source_position=block.source_start + match.start(),
                        message="普通数字引用没有对应的全书尾注定义，保留原文。",
                    )
                )
                continue
            candidates = endnotes_by_label[label]
            target = candidates[0] if len(candidates) == 1 else None
            reason = None if target else "全书尾注中存在多个相同数字定义，无法可靠消歧"
            reference_sequence += 1
            reference_id = f"ref-{reference_sequence:04d}"
            references.append(
                EpubReference(
                    reference_id=reference_id,
                    kind="endnote",
                    label=label,
                    source_start=block.source_start + match.start(),
                    source_end=block.source_start + match.end(),
                    target_note_id=target.note_id if target else None,
                )
            )
            if reason:
                warnings.append(
                    EpubWarning(
                        kind="ambiguous-endnote-reference",
                        label=label,
                        source_position=block.source_start + match.start(),
                        message=reason,
                    )
                )
    return references, warnings


def parse_epub_document(
    text: str,
    *,
    title: str,
    author: str | None = None,
    language: str = "zh-CN",
) -> EpubBookDocument:
    """把整合后的 OCR TXT 解析成 EPUB 语义模型。"""
    normalized_text = _normalize_source_text(text)
    source_lines = _line_spans(normalized_text)
    endnotes, endnote_masks, endnote_warnings = _extract_endnotes(normalized_text, source_lines)
    text_without_endnotes = _apply_masks(normalized_text, endnote_masks)
    lines_without_endnotes = _line_spans(text_without_endnotes)
    footnotes, footnote_masks, footnote_warnings = _extract_footnotes(
        text_without_endnotes,
        lines_without_endnotes,
    )
    body_text = _apply_masks(text_without_endnotes, footnote_masks)
    body_lines = _line_spans(body_text)
    body_blocks = _build_body_blocks(body_text, body_lines)
    references, reference_warnings = _collect_references(body_blocks, tuple(footnotes), tuple(endnotes))
    return EpubBookDocument(
        title=title.strip() or "未命名书籍",
        author=author.strip() if author and author.strip() else None,
        language=language,
        body_blocks=body_blocks,
        footnotes=tuple(footnotes),
        endnotes=tuple(endnotes),
        references=tuple(references),
        warnings=tuple(endnote_warnings + footnote_warnings + reference_warnings),
    )


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _references_for_block(
    block: EpubBodyBlock,
    references: tuple[EpubReference, ...],
) -> list[EpubReference]:
    return sorted(
        (
            reference
            for reference in references
            if block.source_start <= reference.source_start < block.source_end
        ),
        key=lambda reference: reference.source_start,
    )


def _render_inline_text(block: EpubBodyBlock, references: list[EpubReference]) -> str:
    cursor = 0
    rendered: list[str] = []
    for reference in references:
        local_start = reference.source_start - block.source_start
        local_end = reference.source_end - block.source_start
        if local_start < cursor or local_end > len(block.text):
            raise EpubExportError(f"引用位置超出正文块范围: {reference.reference_id}")
        rendered.append(_escape(block.text[cursor:local_start]))
        marker = block.text[local_start:local_end]
        if reference.target_note_id:
            rendered.append(
                f'<a id="{_escape(reference.reference_id)}" '
                f'epub:type="noteref" href="../notes.xhtml#{_escape(reference.target_note_id)}">'
                f"{_escape(marker)}</a>"
            )
        else:
            rendered.append(_escape(marker))
        cursor = local_end
    rendered.append(_escape(block.text[cursor:]))
    return "".join(rendered)


def _render_body_xhtml(document: EpubBookDocument) -> str:
    body_parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE html>',
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{_escape(document.language)}" xml:lang="{_escape(document.language)}">',
        "<head>",
        f"<title>{_escape(document.title)}</title>",
        '<link rel="stylesheet" type="text/css" href="../styles.css" />',
        "</head>",
        "<body>",
        f'<h1 id="book-title">{_escape(document.title)}</h1>',
    ]
    if document.author:
        body_parts.append(f'<p class="author">{_escape(document.author)}</p>')
    for block in document.body_blocks:
        references = _references_for_block(block, document.references)
        content = _render_inline_text(block, references)
        if block.heading_level is None:
            body_parts.append(f'<p id="{_escape(block.block_id)}">{content}</p>')
        else:
            body_parts.append(
                f'<h{block.heading_level} id="{_escape(block.block_id)}">{content}</h{block.heading_level}>'
            )
    body_parts.extend(["</body>", "</html>"])
    return "\n".join(body_parts) + "\n"


def _render_note_body(note: EpubNote, references: list[EpubReference]) -> str:
    backlinks: list[str] = []
    for reference in references:
        backlinks.append(
            f'<a epub:type="backlink" href="text/book.xhtml#{_escape(reference.reference_id)}">'
            f"↩ 返回正文 { _escape(reference.label) }</a>"
        )
    if not backlinks:
        backlinks.append('<span class="unreferenced">（正文没有可靠配对的引用）</span>')
    return (
        f'<aside id="{_escape(note.note_id)}" epub:type="{note.kind}">'
        f'<p><span class="note-label">{_escape(note.label)}</span> '
        f"{_escape(note.body)}</p>"
        f'<p class="backlinks">{" ".join(backlinks)}</p>'
        "</aside>"
    )


def _render_notes_xhtml(document: EpubBookDocument) -> str:
    references_by_note: dict[str, list[EpubReference]] = {}
    for reference in document.references:
        if reference.target_note_id:
            references_by_note.setdefault(reference.target_note_id, []).append(reference)

    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE html>',
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{_escape(document.language)}" xml:lang="{_escape(document.language)}">',
        "<head>",
        "<title>脚注与尾注</title>",
        '<link rel="stylesheet" type="text/css" href="styles.css" />',
        "</head>",
        "<body>",
        "<h1>脚注与尾注</h1>",
    ]
    if document.footnotes:
        parts.extend(['<section id="footnotes" epub:type="footnotes">', "<h2>脚注</h2>"])
        for note in document.footnotes:
            parts.append(_render_note_body(note, references_by_note.get(note.note_id, [])))
        parts.append("</section>")
    if document.endnotes:
        parts.extend(['<section id="endnotes" epub:type="endnotes">', "<h2>尾注</h2>"])
        for note in document.endnotes:
            parts.append(_render_note_body(note, references_by_note.get(note.note_id, [])))
        parts.append("</section>")
    if not document.footnotes and not document.endnotes:
        parts.append("<p>本书没有在整合 TXT 中识别到可独立链接的脚注或尾注。</p>")
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts) + "\n"


def _render_nav_xhtml(document: EpubBookDocument) -> str:
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE html>',
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{_escape(document.language)}" xml:lang="{_escape(document.language)}">',
        "<head>",
        "<title>目录</title>",
        "</head>",
        "<body>",
        '<nav epub:type="toc" id="toc">',
        "<h1>目录</h1>",
        "<ol>",
        f'<li><a href="text/book.xhtml#book-title">{_escape(document.title)}</a></li>',
    ]
    for block in document.body_blocks:
        if block.heading_level is not None:
            parts.append(
                f'<li><a href="text/book.xhtml#{_escape(block.block_id)}">{_escape(block.text)}</a></li>'
            )
    parts.extend([
        '<li><a href="notes.xhtml">脚注与尾注</a></li>',
        "</ol>",
        "</nav>",
        "</body>",
        "</html>",
    ])
    return "\n".join(parts) + "\n"


def _render_container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""


def _render_content_opf(document: EpubBookDocument, source_text: str) -> str:
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"{document.title}:{digest}")
    modified = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    author = f"<dc:creator>{_escape(document.author)}</dc:creator>" if document.author else ""
    return f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         unique-identifier="pub-id" version="3.0">
  <metadata>
    <dc:identifier id="pub-id">urn:uuid:{identifier}</dc:identifier>
    <dc:title>{_escape(document.title)}</dc:title>
    {author}
    <dc:language>{_escape(document.language)}</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
    <item id="book" href="text/book.xhtml" media-type="application/xhtml+xml" />
    <item id="notes" href="notes.xhtml" media-type="application/xhtml+xml" />
    <item id="css" href="styles.css" media-type="text/css" />
  </manifest>
  <spine>
    <itemref idref="book" />
    <itemref idref="notes" />
  </spine>
</package>
'''


def _render_styles() -> str:
    return """body { line-height: 1.8; margin: 1em; }
h1, h2, h3 { line-height: 1.35; }
p { text-indent: 2em; margin: 0.7em 0; }
.author { text-align: center; text-indent: 0; }
.note-label { font-weight: bold; }
.backlinks { text-indent: 0; font-size: 0.9em; }
.unreferenced { color: #666; }
"""


def build_epub_bytes(document: EpubBookDocument, source_text: str) -> bytes:
    """把语义模型封装为 EPUB 3 ZIP 字节。"""
    entries = [
        ("META-INF/container.xml", _render_container_xml().encode("utf-8")),
        ("OEBPS/content.opf", _render_content_opf(document, source_text).encode("utf-8")),
        ("OEBPS/nav.xhtml", _render_nav_xhtml(document).encode("utf-8")),
        ("OEBPS/text/book.xhtml", _render_body_xhtml(document).encode("utf-8")),
        ("OEBPS/notes.xhtml", _render_notes_xhtml(document).encode("utf-8")),
        ("OEBPS/styles.css", _render_styles().encode("utf-8")),
    ]
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.date_time = (1980, 1, 1, 0, 0, 0)
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        for name, content in entries:
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def build_default_epub_output_path(input_path: Path) -> Path:
    """构造整合 TXT 对应的默认 EPUB 输出路径。"""
    return input_path.expanduser().resolve().with_suffix(".epub")


def export_epub(
    input_text_path: Path,
    output_path: Path | None = None,
    *,
    title: str | None = None,
    author: str | None = None,
    language: str = "zh-CN",
) -> EpubExportResult:
    """读取整合后的 TXT 并生成 EPUB 3 文件。"""
    resolved_input = input_text_path.expanduser().resolve()
    if not resolved_input.is_file():
        raise EpubExportError(f"输入整合 TXT 不存在: {resolved_input}")
    if resolved_input.suffix.lower() != ".txt":
        raise EpubExportError(f"EPUB 输入必须是 TXT: {resolved_input}")

    resolved_output = (
        output_path.expanduser().resolve()
        if output_path is not None
        else build_default_epub_output_path(resolved_input)
    )
    if resolved_input == resolved_output:
        raise EpubExportError(f"EPUB 输出路径不能覆盖输入 TXT: {resolved_input}")
    if resolved_output.exists() and resolved_output.is_dir():
        raise EpubExportError(f"EPUB 输出路径是文件夹: {resolved_output}")

    try:
        source_text = resolved_input.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise EpubExportError(f"无法读取整合 TXT: {resolved_input} | {exc}") from exc
    except UnicodeDecodeError as exc:
        raise EpubExportError(f"整合 TXT 不是有效的 UTF-8 文本: {resolved_input} | {exc}") from exc

    document = parse_epub_document(
        source_text,
        title=title or resolved_input.stem,
        author=author,
        language=language,
    )
    epub_bytes = build_epub_bytes(document, source_text)
    try:
        ensure_directory(resolved_output.parent)
        resolved_output.write_bytes(epub_bytes)
    except OSError as exc:
        raise EpubExportError(f"无法写入 EPUB: {resolved_output} | {exc}") from exc
    return EpubExportResult(output_path=resolved_output, document=document)
