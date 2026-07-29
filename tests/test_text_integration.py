from __future__ import annotations

from pathlib import Path

import pytest

from src.text_integration import TextIntegrationError, integrate_ocr_texts


def test_integrate_directory_uses_natural_order_and_preserves_source_files(tmp_path: Path) -> None:
    fragments = tmp_path / "fragments"
    fragments.mkdir()
    source_contents = {
        "page-10.txt": "第十页\n",
        "page-2.txt": "第二页\r\n",
        "page-1.txt": "第一页",
    }
    for name, content in source_contents.items():
        (fragments / name).write_text(content, encoding="utf-8")

    output = tmp_path / "book.txt"
    result = integrate_ocr_texts(fragments, output)

    assert [path.name for path in result.source_paths] == ["page-1.txt", "page-2.txt", "page-10.txt"]
    assert output.read_text(encoding="utf-8") == "第一页\n第二页\n第十页"
    assert (fragments / "page-1.txt").read_text(encoding="utf-8") == "第一页"
    assert result.character_count == len("第一页\n第二页\n第十页")


def test_integrate_single_txt_normalizes_bom_and_newlines_without_overwriting_source(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("第一行\r\n第二行\r第三行\n", encoding="utf-8-sig")
    output = tmp_path / "integrated.txt"

    integrate_ocr_texts(source, output)

    assert output.read_text(encoding="utf-8") == "第一行\n第二行\n第三行"
    assert source.read_bytes().startswith(b"\xef\xbb\xbf")


def test_integrate_rejects_same_input_and_output(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("正文", encoding="utf-8")

    with pytest.raises(TextIntegrationError, match="拒绝覆盖源文件"):
        integrate_ocr_texts(source, source)


def test_integrate_rejects_directory_without_txt(tmp_path: Path) -> None:
    with pytest.raises(TextIntegrationError, match="没有找到 TXT"):
        integrate_ocr_texts(tmp_path, tmp_path / "out.txt")
