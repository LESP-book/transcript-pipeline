from __future__ import annotations

import errno
import logging
from email.message import Message
from pathlib import Path

import yaml

from src.config_loader import load_settings
from src.job_runner import (
    BatchJobRuntime,
    BatchJobSpec,
    BatchRunSummary,
    CANONICAL_INPUT_BASENAME,
    build_job_paths,
    build_job_initial_prompt,
    detect_reference_source_type,
    fetch_reference_from_url,
    get_batch_exit_code,
    load_batch_job_specs,
    prepare_job_inputs,
    run_batch_jobs,
    run_batch_stage,
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


def test_load_batch_job_specs_from_manifest_keeps_valid_items_and_records_invalid_entries(
    tmp_path: Path,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    output_dir = tmp_path / "deliverables"
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = tmp_path / "lesson.mp4"
    reference_path = tmp_path / "chapter.txt"
    glossary_path = tmp_path / "glossary.txt"
    video_path.write_bytes(b"video")
    reference_path.write_text("参考原文", encoding="utf-8")
    glossary_path.write_text("术语", encoding="utf-8")

    manifest_path = tmp_path / "jobs.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "video": str(video_path),
                        "reference": str(reference_path),
                        "output_dir": str(output_dir),
                        "book_name": "书名",
                        "chapter": "第一章",
                        "glossary_file": str(glossary_path),
                    },
                    {
                        "video": str(video_path),
                        "output_dir": str(output_dir),
                    },
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    specs, failed_items = load_batch_job_specs(
        base_loaded_settings=loaded_settings,
        manifest=str(manifest_path),
    )

    assert len(specs) == 1
    assert specs[0] == BatchJobSpec(
        video=str(video_path.resolve()),
        reference=str(reference_path.resolve()),
        output_dir=str(output_dir.resolve()),
        mode="manifest",
        book_name="书名",
        chapter="第一章",
        glossary_file=str(glossary_path.resolve()),
    )
    assert len(failed_items) == 1
    assert failed_items[0].status == "failed"
    assert failed_items[0].failed_stage == "input-validation"
    assert "缺少必填字段" in (failed_items[0].error_message or "")


def test_load_batch_job_specs_pairs_directory_inputs_and_marks_missing_reference_and_invalid_extension(
    tmp_path: Path,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    videos_dir = tmp_path / "videos"
    reference_dir = tmp_path / "reference"
    output_dir = tmp_path / "deliverables"
    videos_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    (videos_dir / "lesson-a.mp4").write_bytes(b"video-a")
    (videos_dir / "lesson-b.mp4").write_bytes(b"video-b")
    (videos_dir / "notes.txt").write_text("not-video", encoding="utf-8")
    (reference_dir / "lesson-a.txt").write_text("参考 A", encoding="utf-8")

    specs, failed_items = load_batch_job_specs(
        base_loaded_settings=loaded_settings,
        videos_dir=str(videos_dir),
        reference_dir=str(reference_dir),
        output_dir=str(output_dir),
    )

    assert len(specs) == 1
    assert specs[0].mode == "paired-dir"
    assert Path(specs[0].video) == (videos_dir / "lesson-a.mp4").resolve()
    assert Path(specs[0].reference) == (reference_dir / "lesson-a.txt").resolve()
    assert Path(specs[0].output_dir) == output_dir.resolve()

    assert len(failed_items) == 2
    error_messages = {item.error_message or "" for item in failed_items}
    assert any("缺少匹配的 reference" in message for message in error_messages)
    assert any("不支持的视频扩展名" in message for message in error_messages)


def test_load_batch_job_specs_marks_duplicate_targets_as_failed(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    videos_dir = tmp_path / "videos"
    reference_dir = tmp_path / "reference"
    output_dir = tmp_path / "deliverables"
    videos_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    (videos_dir / "lesson-a.mp4").write_bytes(b"video-a")
    (videos_dir / "lesson-b.mp4").write_bytes(b"video-b")
    (reference_dir / "lesson-a.txt").write_text("参考 A", encoding="utf-8")
    (reference_dir / "lesson-b.txt").write_text("参考 B", encoding="utf-8")

    specs, failed_items = load_batch_job_specs(
        base_loaded_settings=loaded_settings,
        videos_dir=str(videos_dir),
        reference_dir=str(reference_dir),
        output_dir=str(output_dir),
        book_name="同一本书",
        chapter="同一章",
    )

    assert specs == []
    assert len(failed_items) == 2
    assert all(item.failed_stage == "input-validation" for item in failed_items)
    assert all("重复 target" in (item.error_message or "") for item in failed_items)


def test_load_batch_job_specs_supports_shared_reference_mode(tmp_path: Path) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    videos_dir = tmp_path / "videos"
    output_dir = tmp_path / "deliverables"
    shared_reference = tmp_path / "shared.txt"
    videos_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    shared_reference.write_text("共享参考", encoding="utf-8")

    (videos_dir / "lesson-a.mp4").write_bytes(b"video-a")
    (videos_dir / "lesson-b.mp4").write_bytes(b"video-b")

    specs, failed_items = load_batch_job_specs(
        base_loaded_settings=loaded_settings,
        videos_dir=str(videos_dir),
        shared_reference=str(shared_reference),
        output_dir=str(output_dir),
    )

    assert len(specs) == 2
    assert failed_items == []
    assert all(spec.mode == "shared-reference" for spec in specs)
    assert {Path(spec.video).name for spec in specs} == {"lesson-a.mp4", "lesson-b.mp4"}
    assert all(Path(spec.reference) == shared_reference.resolve() for spec in specs)


def test_run_batch_stage_uses_limited_concurrency_for_remote_stages(tmp_path: Path, monkeypatch) -> None:
    runtime = BatchJobRuntime(
        job_id="job-a",
        job_root=tmp_path / "data/jobs/job-a",
        spec=BatchJobSpec(
            video=str((tmp_path / "lesson-a.mp4").resolve()),
            reference=str((tmp_path / "lesson-a.txt").resolve()),
            output_dir=str((tmp_path / "deliverables").resolve()),
            mode="manifest",
        ),
        status="pending",
    )
    calls: list[tuple[str, int, list[str]]] = []

    def fake_run_jobs_with_limited_concurrency(*, stage_name, runtimes, remote_concurrency, **_kwargs) -> None:
        calls.append((stage_name, remote_concurrency, [item.job_id for item in runtimes]))

    monkeypatch.setattr("src.job_runner.run_jobs_with_limited_concurrency", fake_run_jobs_with_limited_concurrency)

    run_batch_stage(
        stage_name="prepare-reference",
        runtimes=[runtime],
        project_root=tmp_path,
        logger=logging.getLogger("test-batch"),
        remote_concurrency=3,
    )

    assert calls == [("prepare-reference", 3, ["job-a"])]


def test_run_batch_jobs_marks_failed_stage_skips_later_stages_and_records_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    write_minimal_settings(tmp_path)
    loaded_settings = load_settings(project_root=tmp_path)

    output_dir = tmp_path / "deliverables"
    output_dir.mkdir(parents=True, exist_ok=True)

    video_a = tmp_path / "lesson-a.mp4"
    video_b = tmp_path / "lesson-b.mp4"
    reference_a = tmp_path / "lesson-a.txt"
    reference_b = tmp_path / "lesson-b.txt"
    video_a.write_bytes(b"video-a")
    video_b.write_bytes(b"video-b")
    reference_a.write_text("参考 A", encoding="utf-8")
    reference_b.write_text("参考 B", encoding="utf-8")

    created_job_ids = iter(["job-a", "job-b"])
    monkeypatch.setattr("src.job_runner.create_job_id", lambda: next(created_job_ids))

    stage_calls: list[tuple[str, str]] = []

    def fake_run_stage(stage_name, job_loaded_settings, logger) -> int:
        _ = logger
        job_id = job_loaded_settings.path_for("videos_dir").parents[1].name
        stage_calls.append((stage_name, job_id))
        if stage_name == "prepare-reference" and job_id == "job-b":
            return 1
        if stage_name == "export-markdown" and job_id == "job-a":
            final_dir = job_loaded_settings.path_for("final_dir")
            final_dir.mkdir(parents=True, exist_ok=True)
            (final_dir / f"{CANONICAL_INPUT_BASENAME}.md").write_text("# 批量输出\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("src.job_runner.run_stage", fake_run_stage)

    summary = run_batch_jobs(
        project_root=tmp_path,
        base_loaded_settings=loaded_settings,
        job_specs=[
            BatchJobSpec(
                video=str(video_a),
                reference=str(reference_a),
                output_dir=str(output_dir),
                mode="manifest",
            ),
            BatchJobSpec(
                video=str(video_b),
                reference=str(reference_b),
                output_dir=str(output_dir),
                mode="manifest",
            ),
        ],
        failed_runtimes=[],
        remote_concurrency=2,
        batch_id="batch-fixed",
    )

    assert summary.batch_id == "batch-fixed"
    assert summary.total == 2
    assert summary.success == 1
    assert summary.failed == 1

    items_by_job_id = {item.job_id: item for item in summary.items}
    assert items_by_job_id["job-a"].status == "success"
    assert items_by_job_id["job-a"].copied_output_path == output_dir / "lesson-a.md"
    assert items_by_job_id["job-a"].copied_output_path.read_text(encoding="utf-8") == "# 批量输出\n"
    assert items_by_job_id["job-b"].status == "failed"
    assert items_by_job_id["job-b"].failed_stage == "prepare-reference"
    assert "exit_code=1" in (items_by_job_id["job-b"].error_message or "")

    assert ("refine", "job-b") not in stage_calls
    assert ("export-markdown", "job-b") not in stage_calls

    summary_path = tmp_path / "data/jobs/batches/batch-fixed/summary.json"
    assert summary_path.exists()
    summary_payload = yaml.safe_load(summary_path.read_text(encoding="utf-8"))
    assert summary_payload["failed"] == 1
    assert summary_payload["items"][0]["copied_output_path"].endswith("lesson-a.md")


def test_get_batch_exit_code_returns_expected_values(tmp_path: Path) -> None:
    spec = BatchJobSpec(
        video=str((tmp_path / "lesson.mp4").resolve()),
        reference=str((tmp_path / "lesson.txt").resolve()),
        output_dir=str((tmp_path / "deliverables").resolve()),
        mode="manifest",
    )

    assert get_batch_exit_code(
        BatchRunSummary(
            batch_id="batch-all-success",
            total=2,
            success=2,
            failed=0,
            items=[
                BatchJobRuntime(job_id="job-a", job_root=tmp_path / "job-a", spec=spec, status="success"),
                BatchJobRuntime(job_id="job-b", job_root=tmp_path / "job-b", spec=spec, status="success"),
            ],
        )
    ) == 0
    assert get_batch_exit_code(
        BatchRunSummary(
            batch_id="batch-partial",
            total=2,
            success=1,
            failed=1,
            items=[
                BatchJobRuntime(job_id="job-a", job_root=tmp_path / "job-a", spec=spec, status="success"),
                BatchJobRuntime(
                    job_id="job-b",
                    job_root=tmp_path / "job-b",
                    spec=spec,
                    status="failed",
                    failed_stage="refine",
                    error_message="boom",
                ),
            ],
        )
    ) == 2
    assert get_batch_exit_code(
        BatchRunSummary(
            batch_id="batch-all-failed",
            total=2,
            success=0,
            failed=2,
            items=[
                BatchJobRuntime(
                    job_id="job-a",
                    job_root=tmp_path / "job-a",
                    spec=spec,
                    status="failed",
                    failed_stage="transcribe",
                    error_message="boom-a",
                ),
                BatchJobRuntime(
                    job_id="job-b",
                    job_root=tmp_path / "job-b",
                    spec=spec,
                    status="failed",
                    failed_stage="refine",
                    error_message="boom-b",
                ),
            ],
        )
    ) == 1
