from __future__ import annotations

import zipfile
from src.epub_export import parse_epub_document
from src.epub_export import export_epub


def test_full_book_endnote_definition_is_matched_across_the_whole_text() -> None:
    document = parse_epub_document(
        "正文中的社会主义者报91。\n1847年12月—1848年1月。\n尾注\n91 这是书末的尾注定义。",
        title="测试书",
    )

    assert [note.label for note in document.endnotes] == ["91"]
    assert len(document.references) == 1
    assert document.references[0].label == "91"
    assert document.references[0].target_note_id == document.endnotes[0].note_id
    assert not any(warning.label in {"1847", "1848"} for warning in document.warnings)


def test_numbered_tail_without_heading_is_matched_when_sequence_and_reference_are_clear() -> None:
    document = parse_epub_document(
        "正文中的社会主义者报87。\n其他正文。\n87 第一条尾注。\n88 第二条尾注。",
        title="测试书",
    )

    assert [note.label for note in document.endnotes] == ["87", "88"]
    assert document.references[0].target_note_id == document.endnotes[0].note_id


def test_duplicate_endnote_definitions_are_not_guessed() -> None:
    document = parse_epub_document(
        "正文中的社会主义者报91。\n尾注\n91 第一条定义。\n91 第二条定义。",
        title="测试书",
    )

    assert len(document.endnotes) == 2
    assert document.references[0].target_note_id is None
    assert any(warning.kind == "ambiguous-endnote-reference" for warning in document.warnings)


def test_missing_endnote_definition_keeps_plain_number_and_reports_warning() -> None:
    document = parse_epub_document(
        "正文中的社会主义者报91。\n1847年12月—1848年1月。",
        title="截取正文",
    )

    assert document.endnotes == ()
    assert len(document.references) == 1
    assert document.references[0].label == "91"
    assert document.references[0].target_note_id is None
    assert any(warning.kind == "unmatched-endnote-reference" for warning in document.warnings)
    assert not any(warning.label in {"1847", "1848"} for warning in document.warnings)


def test_paired_circle_note_does_not_consume_following_heading() -> None:
    document = parse_epub_document(
        "一、资产者和无产者①\n正文内容。\n① 资产阶级定义。（恩格斯在1888年英文版上加的注）一、下一节",
        title="测试书",
    )

    assert len(document.footnotes) == 1
    assert document.footnotes[0].body == "资产阶级定义。（恩格斯在1888年英文版上加的注）"
    assert any(block.text == "一、下一节" for block in document.body_blocks)
    assert document.references[0].target_note_id == document.footnotes[0].note_id


def test_repeated_circle_numbers_are_scoped_by_heading() -> None:
    document = parse_epub_document(
        "一、第一节①\n① 第一条注释——编者注\n二、第二节①\n① 第二条注释——编者注",
        title="测试书",
    )

    assert [note.body for note in document.footnotes] == ["第一条注释——编者注", "第二条注释——编者注"]
    assert [reference.target_note_id for reference in document.references] == [
        document.footnotes[0].note_id,
        document.footnotes[1].note_id,
    ]


def test_uncertain_circle_definition_remains_in_body() -> None:
    document = parse_epub_document(
        "一、正文①\n① 这条注释没有可靠终点\n后续正文不能被吞掉",
        title="测试书",
    )

    assert document.footnotes == ()
    assert any(block.text == "① 这条注释没有可靠终点" for block in document.body_blocks)
    assert any(block.text == "后续正文不能被吞掉" for block in document.body_blocks)
    assert any(warning.kind == "uncertain-footnote-end" for warning in document.warnings)


def test_export_epub_writes_standard_package_and_bidirectional_note_links(tmp_path) -> None:
    source = tmp_path / "测试书.integrated.txt"
    source.write_text(
        "一、正文中的社会主义者报91和圆圈引用①。\n"
        "1847年12月。\n"
        "① 圆圈脚注——编者注\n"
        "尾注\n"
        "91 书末尾注。",
        encoding="utf-8",
    )
    output = tmp_path / "测试书.epub"

    result = export_epub(source, output, title="测试书", author="测试作者")

    assert result.output_path == output.resolve()
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        body = archive.read("OEBPS/text/book.xhtml").decode("utf-8")
        notes = archive.read("OEBPS/notes.xhtml").decode("utf-8")
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")

    assert 'epub:type="noteref"' in body
    assert 'epub:type="footnote"' in notes
    assert 'epub:type="endnote"' in notes
    assert 'epub:type="backlink"' in notes
    assert "测试作者" in opf
    assert "zh-CN" in opf
    assert 'epub:type="toc"' in nav


def test_export_epub_without_notes_is_still_readable(tmp_path) -> None:
    source = tmp_path / "无注释.integrated.txt"
    source.write_text("只有正文。\n1847年。", encoding="utf-8")

    result = export_epub(source)

    assert result.output_path == source.with_suffix(".epub")
    assert result.document.footnotes == ()
    assert result.document.endnotes == ()
    assert result.output_path.is_file()
