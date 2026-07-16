from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from src.schemas import LoadedSettings

PDF_OCR_PROTOCOL_VERSION = "codex-api-image-page-v1"


@dataclass(frozen=True)
class PDFOCRRunIdentity:
    """唯一标识一份 PDF 在一组 OCR 配置下的页检查点。"""

    source_digest: str
    model: str
    reasoning_effort: str
    protocol_version: str = PDF_OCR_PROTOCOL_VERSION

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "source_digest": self.source_digest,
                "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "protocol_version": self.protocol_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {
            "source_digest": self.source_digest,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "protocol_version": self.protocol_version,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class PDFOCRPageState:
    """统一描述一次 PDF OCR 当前已完成页和失败页。"""

    page_count: int
    completed_page_numbers: tuple[int, ...] = ()
    page_errors: dict[int, str] = field(default_factory=dict)

    @property
    def completed_pages(self) -> int:
        return len(self.completed_page_numbers)

    @property
    def failed_page_numbers(self) -> tuple[int, ...]:
        return tuple(sorted(self.page_errors))

    @property
    def resumable(self) -> bool:
        return self.completed_pages < self.page_count


def calculate_file_sha256(source_path: Path) -> str:
    """流式计算文件内容指纹，避免大 PDF 被一次性读入内存。"""
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise OSError(f"无法计算 PDF 内容指纹: {source_path} | {exc}") from exc
    return digest.hexdigest()


def build_pdf_ocr_run_identity(
    source_pdf: Path,
    loaded_settings: LoadedSettings,
) -> PDFOCRRunIdentity:
    reference_settings = loaded_settings.settings.reference
    return PDFOCRRunIdentity(
        source_digest=calculate_file_sha256(source_pdf),
        model=reference_settings.codex_ocr_model.strip(),
        reasoning_effort=reference_settings.codex_ocr_reasoning_effort.strip(),
    )


def build_pdf_ocr_checkpoint_namespace(
    checkpoint_root: Path,
    identity: PDFOCRRunIdentity,
) -> Path:
    return checkpoint_root.expanduser().resolve() / identity.fingerprint
