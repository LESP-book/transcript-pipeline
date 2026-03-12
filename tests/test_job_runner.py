from __future__ import annotations

import errno
from email.message import Message
from pathlib import Path

import yaml

from src.config_loader import load_settings
from src.job_runner import (
    CANONICAL_INPUT_BASENAME,
    build_job_paths,
    build_job_initial_prompt,
    detect_reference_source_type,
    fetch_reference_from_url,
    prepare_job_inputs,
    run_single_job,
    write_job_settings,
)
from tests.helpers import write_minimal_settings


class FakeHTTPResponse:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb


def test_detect_reference_source_type_supports_local_and_url_sources() -> None:
    assert detect_reference_source_type("/tmp/book.txt") == "txt"
    assert detect_reference_source_type("/tmp/book.md") == "md"
    assert detect_reference_source_type("/tmp/book.pdf") == "pdf"
    assert detect_reference_source_type("https://example.com/book") == "url"


def test_prepare_job_inputs_copies_local_pdf_with_canonical_basename(tmp_path: Path) -> None:
    video_path = tmp_path / "lecture.mp4"
    reference_path = tmp_path / "source.pdf"
    video_path.write_bytes(b"video")
    reference_path.write_bytes(b"%PDF-1.4 fake")

    job_paths = build_job_paths(tmp_path, "job-local-pdf")
    prepared = prepare_job_inputs(
        video_source=video_path,
        reference_source=str(reference_path),
        job_paths=job_paths,
    )

    assert prepared.reference_type == "pdf"
    assert prepared.video_path == job_paths.input_videos_dir / f"{CANONICAL_INPUT_BASENAME}.mp4"
    assert prepared.reference_path == job_paths.input_reference_dir / f"{CANONICAL_INPUT_BASENAME}.pdf"
    assert prepared.reference_path.exists()


def test_fetch_reference_from_url_extracts_html_to_txt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination_dir = tmp_path / "input/reference"
    destination_dir.mkdir(parents=True, exist_ok=True)

    html = b"""
    <html><head><title>demo</title></head>
    <body><article><h1>\xe6\xa0\x87\xe9\xa2\x98</h1><p>\xe7\xac\xac\xe4\xb8\x80\xe6\xae\xb5</p><p>\xe7\xac\xac\xe4\xba\x8c\xe6\xae\xb5</p></article></body></html>
    """

    monkeypatch.setattr(
        "src.job_runner.urlopen",
        lambda *_args, **_kwargs: FakeHTTPResponse(html, "text/html; charset=utf-8"),
    )

    output_path, reference_type = fetch_reference_from_url(
        "https://example.com/article",
        destination_dir,
        CANONICAL_INPUT_BASENAME,
    )

    assert reference_type == "url_text"
    assert output_path == destination_dir / f"{CANONICAL_INPUT_BASENAME}.txt"
    content = output_path.read_text(encoding="utf-8")
    assert "标题" in content
    assert "第一段" in content
    assert "第二段" in content


def test_fetch_reference_from_url_retries_with_ipv4_when_network_is_unreachable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    destination_dir = tmp_path / "input/reference"
    destination_dir.mkdir(parents=True, exist_ok=True)

    html = b"""
    <html><body><article><p>\xe5\x9b\x9e\xe9\x80\x80\xe6\x88\x90\xe5\x8a\x9f</p></article></body></html>
    """
    calls: list[str] = []

    def fake_urlopen(*_args, **_kwargs):
        if not calls:
            calls.append("first_attempt")
            raise OSError(errno.ENETUNREACH, "Network is unreachable")
        calls.append("retry_attempt")
        return FakeHTTPResponse(html, "text/html; charset=utf-8")

    monkeypatch.setattr("src.job_runner.urlopen", fake_urlopen)

    output_path, reference_type = fetch_reference_from_url(
        "https://example.com/article",
        destination_dir,
        CANONICAL_INPUT_BASENAME,
    )

    assert reference_type == "url_text"
    assert output_path == destination_dir / f"{CANONICAL_INPUT_BASENAME}.txt"
    assert output_path.read_text(encoding="utf-8") == "回退成功"
    assert calls == ["first_attempt", "retry_attempt"]


def test_write_job_settings_rewrites_paths_into_job_workspace(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    glossary_dir = tmp_path / "config/glossaries"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "marxism_common.txt").write_text("马克思\n恩格斯\n", encoding="utf-8")
    loaded_settings = load_settings(project_root=tmp_path)
    job_paths = build_job_paths(tmp_path, "job-settings")

    settings_path = write_job_settings(
        project_root=tmp_path,
        loaded_settings=loaded_settings,
        job_paths=job_paths,
        profile_name="local_cpu",
    )

    payload = yaml.safe_load(settings_path.read_text(encoding="utf-8"))

    assert payload["paths"]["videos_dir"] == str(job_paths.input_videos_dir)
    assert payload["paths"]["reference_dir"] == str(job_paths.input_reference_dir)
    assert payload["paths"]["asr_dir"] == str(job_paths.intermediate_asr_dir)
    assert payload["paths"]["final_dir"] == str(job_paths.output_final_dir)
    assert payload["runtime"]["profile"] == "local_cpu"
    assert payload["asr"]["initial_prompt"]


def test_build_job_initial_prompt_includes_title_and_extra_glossary(tmp_path: Path) -> None:
    glossary_dir = tmp_path / "config/glossaries"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "marxism_common.txt").write_text("马克思\n恩格斯\n", encoding="utf-8")
    extra_glossary = tmp_path / "chapter_terms.txt"
    extra_glossary.write_text("摩尔根\n氏族\n", encoding="utf-8")

    prompt = build_job_initial_prompt(
        project_root=tmp_path,
        glossary_file=str(extra_glossary),
        book_name="家庭、私有制和国家的起源",
        chapter="第八章",
        max_chars=200,
    )

    assert "家庭、私有制和国家的起源" in prompt
    assert "第八章" in prompt
    assert "马克思" in prompt
    assert "摩尔根" in prompt


def test_build_job_initial_prompt_prioritizes_job_specific_terms_before_common_terms(tmp_path: Path) -> None:
    glossary_dir = tmp_path / "config/glossaries"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "marxism_common.txt").write_text("马克思\n恩格斯\n列宁\n斯大林\n", encoding="utf-8")
    extra_glossary = tmp_path / "chapter_terms.txt"
    extra_glossary.write_text("摩尔根\n氏族\n", encoding="utf-8")

    prompt = build_job_initial_prompt(
        project_root=tmp_path,
        glossary_file=str(extra_glossary),
        book_name="家庭、私有制和国家的起源",
        chapter="第八章",
        max_chars=22,
    )

    assert prompt == "家庭、私有制和国家的起源，第八章，摩尔根"


def test_run_single_job_copies_final_markdown_to_output_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    video_path = tmp_path / "lesson.mp4"
    reference_path = tmp_path / "chapter.txt"
    output_dir = tmp_path / "deliverables"
    video_path.write_bytes(b"video")
    reference_path.write_text("参考原文", encoding="utf-8")

    monkeypatch.setattr("src.job_runner.create_job_id", lambda: "job-fixed-id")

    def fake_run_job_pipeline(job_loaded_settings, logger) -> None:
        _ = logger
        final_dir = job_loaded_settings.path_for("final_dir")
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / f"{CANONICAL_INPUT_BASENAME}.md").write_text("# 最终稿\n\n正文", encoding="utf-8")

    monkeypatch.setattr("src.job_runner.run_job_pipeline", fake_run_job_pipeline)

    result = run_single_job(
        project_root=tmp_path,
        base_loaded_settings=loaded_settings,
        video=str(video_path),
        reference=str(reference_path),
        output_dir=str(output_dir),
    )

    assert result.job_id == "job-fixed-id"
    assert result.final_markdown_path.read_text(encoding="utf-8") == "# 最终稿\n\n正文"
    assert result.copied_output_path == output_dir / "lesson.md"
    assert result.copied_output_path.read_text(encoding="utf-8") == "# 最终稿\n\n正文"
    manifest_path = tmp_path / "data/jobs/job-fixed-id/manifest.json"
    assert manifest_path.exists()
