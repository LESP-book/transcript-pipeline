from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "transcript_pipeline"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    level = getattr(logging, log_level.upper(), logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return logger


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def relativize_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root))
    except ValueError:
        return str(path.resolve())


def normalize_stage_name(stage_name: str) -> str:
    normalized = stage_name.strip().lower().replace("_", "-")
    if normalized in {"extract-audio", "transcribe", "prepare-reference", "align", "classify", "refine", "export-markdown"}:
        return normalized
    raise ValueError(
        f"当前阶段仅支持 extract-audio、transcribe、prepare-reference、align、classify、refine 或 export-markdown，收到: {stage_name}"
    )
