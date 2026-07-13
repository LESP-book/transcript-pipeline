from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.reference_utils import CodexOCRError, run_codex_api_pdf_ocr
from src.schemas import LoadedSettings


class PDFBookOCRError(RuntimeError):
    """PDF 书籍 OCR 的输入或执行准备失败。"""


@dataclass(frozen=True)
class PDFBookOCRItem:
    source_pdf: Path
    output_text_path: Path
    success: bool
    text_length: int
    warnings: list[str]
    error: str | None = None


@dataclass(frozen=True)
class PDFBookOCRSummary:
    items: list[PDFBookOCRItem]

    @property
    def success_count(self) -> int:
        return sum(item.success for item in self.items)

    @property
    def failure_count(self) -> int:
        return len(self.items) - self.success_count


def iter_pdf_book_files(input_path: Path) -> list[Path]:
    """返回单个 PDF 或目录中的全部 PDF，并保持稳定的相对路径顺序。"""
    resolved_input_path = input_path.expanduser().resolve()
    if resolved_input_path.is_file():
        if resolved_input_path.suffix.lower() != ".pdf":
            raise PDFBookOCRError(f"输入文件不是 PDF: {resolved_input_path}")
        return [resolved_input_path]

    if not resolved_input_path.is_dir():
        raise PDFBookOCRError(f"输入路径不存在或不是文件夹: {resolved_input_path}")

    pdf_files = sorted(
        (
            path.resolve()
            for path in resolved_input_path.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: path.relative_to(resolved_input_path).as_posix().lower(),
    )
    if not pdf_files:
        raise PDFBookOCRError(f"输入文件夹中没有找到 PDF: {resolved_input_path}")
    return pdf_files


def build_pdf_book_output_path(input_path: Path, source_pdf: Path, output_dir: Path) -> Path:
    """为单本或批量书籍构造 TXT 输出路径，批量模式保留目录层级。"""
    resolved_input_path = input_path.expanduser().resolve()
    resolved_source_pdf = source_pdf.expanduser().resolve()
    resolved_output_dir = output_dir.expanduser().resolve()

    if resolved_input_path.is_dir():
        try:
            relative_pdf_path = resolved_source_pdf.relative_to(resolved_input_path)
        except ValueError as exc:
            raise PDFBookOCRError(
                f"PDF 不在输入文件夹内，无法确定输出路径: {resolved_source_pdf}"
            ) from exc
    else:
        relative_pdf_path = Path(resolved_source_pdf.name)

    return resolved_output_dir / relative_pdf_path.with_suffix(".txt")


def ocr_pdf_book(
    source_pdf: Path,
    output_text_path: Path,
    loaded_settings: LoadedSettings,
) -> PDFBookOCRItem:
    """识别单本 PDF；只有整本各页都成功时才写出该书 TXT。"""
    resolved_source_pdf = source_pdf.expanduser().resolve()
    resolved_output_text_path = output_text_path.expanduser().resolve()

    try:
        text, warnings = run_codex_api_pdf_ocr(
            resolved_source_pdf,
            loaded_settings,
            sidecar_path=resolved_output_text_path,
        )
    except CodexOCRError as exc:
        return PDFBookOCRItem(
            source_pdf=resolved_source_pdf,
            output_text_path=resolved_output_text_path,
            success=False,
            text_length=0,
            warnings=[],
            error=str(exc),
        )

    return PDFBookOCRItem(
        source_pdf=resolved_source_pdf,
        output_text_path=resolved_output_text_path,
        success=True,
        text_length=len(text),
        warnings=warnings,
    )


def ocr_pdf_book_batch(
    input_path: Path,
    output_dir: Path,
    loaded_settings: LoadedSettings,
) -> PDFBookOCRSummary:
    """批量识别 PDF 书籍；一本失败不会阻止其余书籍继续处理。"""
    source_pdfs = iter_pdf_book_files(input_path)
    items = [
        ocr_pdf_book(
            source_pdf,
            build_pdf_book_output_path(input_path, source_pdf, output_dir),
            loaded_settings,
        )
        for source_pdf in source_pdfs
    ]
    return PDFBookOCRSummary(items=items)


def summarize_pdf_book_ocr(summary: PDFBookOCRSummary) -> str:
    return f"total={len(summary.items)}, success={summary.success_count}, failed={summary.failure_count}"
