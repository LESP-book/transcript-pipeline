from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.runtime_utils import ensure_directory, relativize_path
from src.schemas import LoadedSettings

REASON_NO_REFERENCE_SIGNAL_DEFAULT_TO_LECTURE = "no_reference_signal_default_to_lecture"
REASON_INTRO_KEYWORDS_DETECTED = "intro_keywords_detected"
REASON_QA_KEYWORDS_DETECTED = "qa_keywords_or_question_mark_detected"
REASON_HIGH_MATCH_SCORE_AND_CLEAR_MARGIN = "high_match_score_and_clear_margin"
REASON_REFERENCE_FOCUSED_QUOTE_LIKE = "reference_focused_quote_like"
REASON_REFERENCE_OVERLAP_WITH_EXTRA_CONTENT = "reference_overlap_with_extra_content"
REASON_REFERENCE_PRESENT_WITHOUT_LECTURE_MARKERS = "reference_present_without_lecture_markers"
REASON_LECTURE_MARKERS_DETECTED = "lecture_markers_detected"


class ClassificationError(RuntimeError):
    """Raised when candidate classification fails."""


class ClassificationInputEmptyError(ClassificationError):
    """Raised when there are no aligned files to classify."""


@dataclass(frozen=True)
class ClassifiedBlock:
    block_id: int
    start: float
    end: float
    asr_text: str
    matched_reference_text: str
    match_score: float
    match_status: str
    top_matches: list[dict[str, Any]]
    classification: str
    classification_reason: str
    confidence: str


@dataclass(frozen=True)
class ClassificationOutputPath:
    json_path: Path


@dataclass(frozen=True)
class ClassificationBatchItem:
    basename: str
    output_path: Path | None
    success: bool
    skipped: bool
    reason: str | None = None


@dataclass(frozen=True)
class ClassificationBatchSummary:
    total: int
    success: int
    skipped: int
    failed: int
    items: list[ClassificationBatchItem]


def iter_aligned_json_files(aligned_dir: Path) -> list[Path]:
    if not aligned_dir.exists():
        return []
    return sorted(path for path in aligned_dir.iterdir() if path.is_file() and path.suffix.lower() == ".json")


def build_classification_output_path(aligned_json_path: Path, output_dir: Path) -> ClassificationOutputPath:
    return ClassificationOutputPath(json_path=output_dir / f"{aligned_json_path.stem}.json")


def load_aligned_payload(aligned_json_path: Path) -> dict[str, Any]:
    try:
        with aligned_json_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except OSError as exc:
        raise ClassificationError(f"无法读取 aligned 文件: {aligned_json_path.name} | {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ClassificationError(f"aligned JSON 解析失败: {aligned_json_path.name} | {exc}") from exc

    if not isinstance(payload, dict) or "blocks" not in payload:
        raise ClassificationError(f"aligned JSON 结构无效: {aligned_json_path.name}")
    return payload


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def get_top_match_margin(block: dict[str, Any]) -> float:
    top_matches = block.get("top_matches", [])
    if not top_matches:
        return 0.0
    first = float(top_matches[0].get("score", 0.0))
    second = float(top_matches[1].get("score", 0.0)) if len(top_matches) > 1 else 0.0
    return round(first - second, 2)


def looks_like_question(text: str, classification_settings: Any) -> bool:
    return "？" in text or "?" in text or contains_any_keyword(text, classification_settings.qa_keywords)


def looks_like_intro(text: str, classification_settings: Any) -> bool:
    if not classification_settings.enable_intro_candidate:
        return False

    stripped = text.strip()
    return any(stripped.startswith(keyword) for keyword in classification_settings.intro_keywords) or any(
        keyword in stripped for keyword in ["现在播送", "中央人民广播电台", "下面播送"]
    )


def looks_like_lecture(text: str, classification_settings: Any) -> bool:
    return contains_any_keyword(text, classification_settings.lecture_markers)


def has_reference_focus(block: dict[str, Any], classification_settings: Any) -> bool:
    matched_reference_text = str(block.get("matched_reference_text", "")).strip()
    top_matches = block.get("top_matches", [])
    if not matched_reference_text or not top_matches:
        return False

    first_score = float(top_matches[0].get("score", 0.0))
    margin = get_top_match_margin(block)
    return first_score >= classification_settings.quote_like_min_score and (
        len(top_matches) == 1 or margin >= classification_settings.reference_focus_margin
    )


def looks_like_quote_candidate(block: dict[str, Any], classification_settings: Any) -> bool:
    asr_text = str(block.get("asr_text", "")).strip()
    matched_reference_text = str(block.get("matched_reference_text", "")).strip()
    match_score = float(block.get("match_score", 0.0))
    match_status = str(block.get("match_status", "no_match"))
    margin = get_top_match_margin(block)
    text_is_longer_than_reference = len(asr_text) > max(len(matched_reference_text), 1) * 1.35

    if not asr_text or not matched_reference_text:
        return False
    if looks_like_question(asr_text, classification_settings):
        return False
    if looks_like_lecture(asr_text, classification_settings):
        return False
    if looks_like_intro(asr_text, classification_settings):
        return False
    if text_is_longer_than_reference and match_score < classification_settings.quote_score_threshold:
        return False

    strong_quote = (
        match_score >= classification_settings.quote_score_threshold
        and match_status in {"matched", "weak_match"}
        and margin >= classification_settings.quote_margin_threshold
    )
    quote_like = has_reference_focus(block, classification_settings)
    return strong_quote or quote_like


def looks_like_mixed_candidate(block: dict[str, Any], classification_settings: Any) -> bool:
    asr_text = str(block.get("asr_text", "")).strip()
    matched_reference_text = str(block.get("matched_reference_text", "")).strip()
    match_score = float(block.get("match_score", 0.0))

    if not matched_reference_text:
        return False

    intro_signal = contains_any_keyword(asr_text, classification_settings.intro_keywords)
    lecture_signal = looks_like_lecture(asr_text, classification_settings)
    reference_overlap = match_score >= classification_settings.mixed_score_threshold or has_reference_focus(
        block, classification_settings
    )
    text_is_longer_than_reference = len(asr_text) > max(len(matched_reference_text), 1) * 1.35
    return reference_overlap and (intro_signal or lecture_signal or text_is_longer_than_reference)


def classify_block(block: dict[str, Any], loaded_settings: LoadedSettings) -> ClassifiedBlock:
    classification_settings = loaded_settings.settings.classification
    asr_text = str(block.get("asr_text", "")).strip()
    matched_reference_text = str(block.get("matched_reference_text", "")).strip()
    match_score = float(block.get("match_score", 0.0))
    match_status = str(block.get("match_status", "no_match"))
    top_matches = block.get("top_matches", [])
    margin = get_top_match_margin(block)

    classification = "lecture_candidate"
    reason = REASON_NO_REFERENCE_SIGNAL_DEFAULT_TO_LECTURE
    confidence = "low"

    if looks_like_question(asr_text, classification_settings):
        classification = "qa_candidate"
        reason = REASON_QA_KEYWORDS_DETECTED
        confidence = "high" if "？" in asr_text or "?" in asr_text else "medium"
    elif looks_like_intro(asr_text, classification_settings):
        classification = "intro_candidate"
        reason = REASON_INTRO_KEYWORDS_DETECTED
        confidence = "medium"
    elif looks_like_quote_candidate(block, classification_settings):
        classification = "quote_candidate"
        reason = (
            REASON_HIGH_MATCH_SCORE_AND_CLEAR_MARGIN
            if (
                match_score >= classification_settings.quote_score_threshold
                and match_status in {"matched", "weak_match"}
                and margin >= classification_settings.quote_margin_threshold
            )
            else REASON_REFERENCE_FOCUSED_QUOTE_LIKE
        )
        confidence = "high" if match_score >= classification_settings.quote_score_threshold else "medium"
    elif looks_like_mixed_candidate(block, classification_settings):
        classification = "mixed_candidate"
        reason = REASON_REFERENCE_OVERLAP_WITH_EXTRA_CONTENT
        confidence = "medium"
    elif looks_like_lecture(asr_text, classification_settings):
        classification = "lecture_candidate"
        reason = REASON_LECTURE_MARKERS_DETECTED
        confidence = "medium"
    elif matched_reference_text:
        classification = "mixed_candidate"
        reason = REASON_REFERENCE_PRESENT_WITHOUT_LECTURE_MARKERS
        confidence = "low"

    return ClassifiedBlock(
        block_id=int(block.get("block_id", 0)),
        start=float(block.get("start", 0.0)),
        end=float(block.get("end", 0.0)),
        asr_text=asr_text,
        matched_reference_text=matched_reference_text,
        match_score=match_score,
        match_status=match_status,
        top_matches=top_matches,
        classification=classification,
        classification_reason=reason,
        confidence=confidence,
    )


def write_classification_result(
    *,
    aligned_json_path: Path,
    classified_blocks: list[ClassifiedBlock],
    output_path: ClassificationOutputPath,
    loaded_settings: LoadedSettings,
) -> None:
    ensure_directory(output_path.json_path.parent)
    payload = {
        "source_aligned_file": relativize_path(aligned_json_path, loaded_settings.project_root),
        "total_blocks": len(classified_blocks),
        "classified_blocks": [asdict(block) for block in classified_blocks],
    }
    with output_path.json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def classify_batch(
    loaded_settings: LoadedSettings,
    logger: logging.Logger | None = None,
) -> ClassificationBatchSummary:
    aligned_dir = loaded_settings.path_for("aligned_dir")
    output_dir = ensure_directory(loaded_settings.path_for("classified_dir"))
    aligned_files = iter_aligned_json_files(aligned_dir)

    if not aligned_files:
        raise ClassificationInputEmptyError(f"aligned 输入目录中没有可处理的 JSON 文件: {aligned_dir}")

    items: list[ClassificationBatchItem] = []
    success_count = 0

    for aligned_json_path in aligned_files:
        payload = load_aligned_payload(aligned_json_path)
        classified_blocks = [classify_block(block, loaded_settings) for block in payload.get("blocks", [])]
        output_path = build_classification_output_path(aligned_json_path, output_dir)
        write_classification_result(
            aligned_json_path=aligned_json_path,
            classified_blocks=classified_blocks,
            output_path=output_path,
            loaded_settings=loaded_settings,
        )
        items.append(
            ClassificationBatchItem(
                basename=aligned_json_path.stem,
                output_path=output_path.json_path,
                success=True,
                skipped=False,
            )
        )
        success_count += 1
        if logger:
            logger.info("候选分类完成 | %s | blocks=%s", aligned_json_path.stem, len(classified_blocks))

    return ClassificationBatchSummary(
        total=len(aligned_files),
        success=success_count,
        skipped=0,
        failed=0,
        items=items,
    )


def summarize_classification_results(summary: ClassificationBatchSummary) -> str:
    return (
        f"total={summary.total}, success={summary.success}, "
        f"skipped={summary.skipped}, failed={summary.failed}"
    )
