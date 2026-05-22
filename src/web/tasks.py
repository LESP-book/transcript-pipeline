from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from scripts.run_pipeline import run_stage
from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import (
    BatchRunSummary,
    JobRunnerError,
    build_batch_root,
    build_final_output_filename,
    build_job_paths,
    copy_final_output,
    load_batch_job_specs,
    prepare_batch_jobs,
    prepare_job_inputs,
    serialize_batch_runtime,
    write_batch_summary,
    write_job_manifest,
    write_job_settings,
)
from src.runtime_utils import normalize_stage_name, setup_logging
from src.settings_overrides import ModelOverrides, apply_model_overrides
from src.web.frontend_settings import (
    codex_lb_environment,
    load_frontend_settings,
)
from src.web.models import BatchJobRequest, JobRerunRequest, SingleJobRequest, StageRunRequest


def first_text(*values: str | None) -> str | None:
    for value in values:
        normalized = (value or "").strip()
        if normalized:
            return normalized
    return None


def stage_output_path(loaded_settings, stage_name: str) -> str:
    field_map = {
        "extract-audio": "audio_dir",
        "transcribe": "asr_dir",
        "prepare-reference": "extracted_text_dir",
        "align": "aligned_dir",
        "classify": "classified_dir",
        "refine": "refined_dir",
        "export-markdown": "final_dir",
    }
    field_name = field_map.get(stage_name)
    if field_name is None:
        return ""
    return str(loaded_settings.path_for(field_name))


def submit_task(fastapi_app: FastAPI, func, **kwargs) -> None:
    if fastapi_app.state.run_tasks_inline:
        func(**kwargs)
        return
    fastapi_app.state.executor.submit(func, **kwargs)


def read_job_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobRunnerError(f"无法读取 job manifest: {manifest_path} | {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JobRunnerError(f"job manifest JSON 解析失败: {manifest_path} | {exc}") from exc
    if not isinstance(payload, dict):
        raise JobRunnerError(f"job manifest 结构无效: {manifest_path}")
    return payload


def resolve_rerun_stages(raw_stages: list[str], start_stage: str) -> list[str]:
    stages = [normalize_stage_name(stage_name) for stage_name in raw_stages]
    normalized_start_stage = normalize_stage_name(start_stage)
    if normalized_start_stage not in stages:
        raise JobRunnerError(
            f"无法从指定阶段重跑: {normalized_start_stage} 不在当前 job 流水线中，当前阶段为: {', '.join(stages)}"
        )
    return stages[stages.index(normalized_start_stage) :]


def execute_single_job(*, app: FastAPI, job_id: str, payload: dict) -> None:
    state_path = app.state.job_state_path(job_id)
    root = app.state.project_root

    app.state.active_jobs.add(job_id)
    try:
        request = SingleJobRequest.model_validate(payload)
        frontend_settings = load_frontend_settings(root)
        effective_profile = first_text(request.profile, frontend_settings.profile)
        effective_backend = first_text(request.backend, frontend_settings.backend)
        effective_book_name = first_text(request.book_name, frontend_settings.book_name)
        effective_chapter = first_text(request.chapter, frontend_settings.chapter)
        effective_glossary_file = first_text(request.glossary_file, frontend_settings.glossary_file)
        model_overrides = ModelOverrides(
            llm_model=request.model or frontend_settings.model or None,
            llm_reasoning_effort=request.reasoning_effort or frontend_settings.reasoning_effort or None,
            ocr_backend=request.ocr_backend or frontend_settings.ocr_backend or None,
            ocr_model=request.ocr_model or frontend_settings.ocr_model or None,
            ocr_reasoning_effort=request.ocr_reasoning_effort or frontend_settings.ocr_reasoning_effort or None,
        )
        base_loaded_settings = load_settings(
            settings_path=request.config,
            profile_name=effective_profile,
            project_root=root,
        )
        profile_name = effective_profile or base_loaded_settings.active_profile_name
        video_source = Path(request.video).expanduser().resolve()
        output_dir = Path(request.output_dir).expanduser().resolve()

        job_paths = build_job_paths(root, job_id)
        prepared_inputs = prepare_job_inputs(
            video_source=video_source,
            reference_source=request.reference,
            job_paths=job_paths,
        )
        generated_settings_path = write_job_settings(
            project_root=root,
            loaded_settings=base_loaded_settings,
            job_paths=job_paths,
            profile_name=profile_name,
            glossary_file=effective_glossary_file,
            book_name=effective_book_name,
            chapter=effective_chapter,
            model_overrides=model_overrides,
        )
        write_job_manifest(
            loaded_settings=base_loaded_settings,
            job_paths=job_paths,
            prepared_inputs=prepared_inputs,
            video_source=video_source,
            reference_source=request.reference,
            output_dir=output_dir,
            profile_name=profile_name,
            book_name=effective_book_name,
            chapter=effective_chapter,
            glossary_file=effective_glossary_file,
        )

        job_loaded_settings = load_settings(
            settings_path=generated_settings_path,
            profile_name=profile_name,
            project_root=root,
        )
        logger = setup_logging(job_loaded_settings.settings.runtime.log_level)
        stages = [normalize_stage_name(stage_name) for stage_name in job_loaded_settings.settings.pipeline.stages]

        with codex_lb_environment(frontend_settings):
            for stage_name in stages:
                app.state.update_state(
                    state_path,
                    status="running",
                    current_stage=stage_name,
                )
                current_backend = effective_backend if stage_name == "refine" else None
                exit_code = run_stage(stage_name, job_loaded_settings, logger, backend_override=current_backend)
                if exit_code != 0:
                    raise JobRunnerError(f"job 主链失败: stage={stage_name} exit_code={exit_code}")

        _, copied_output_path = copy_final_output(
            job_paths,
            output_dir,
            build_final_output_filename(
                video_source,
                book_name=effective_book_name,
                chapter=effective_chapter,
            ),
        )
        app.state.update_state(
            state_path,
            status="success",
            current_stage="done",
            output_path=str(copied_output_path),
        )
    except (ConfigLoadError, JobRunnerError, ValueError, OSError) as exc:
        app.state.update_state(
            state_path,
            status="failed",
            error_message=str(exc),
        )
    finally:
        app.state.active_jobs.discard(job_id)


def execute_job_rerun(*, app: FastAPI, job_id: str, payload: dict) -> None:
    state_path = app.state.job_state_path(job_id)
    root = app.state.project_root

    app.state.active_jobs.add(job_id)
    try:
        request = JobRerunRequest.model_validate(payload)
        frontend_settings = load_frontend_settings(root)
        effective_profile = first_text(request.profile, frontend_settings.profile)
        effective_backend = first_text(request.backend, frontend_settings.backend)
        job_paths = build_job_paths(root, job_id)
        if not job_paths.settings_path.exists():
            raise JobRunnerError(f"job 缺少生成配置，无法重跑: {job_paths.settings_path}")
        if not job_paths.manifest_path.exists():
            raise JobRunnerError(f"job 缺少 manifest，无法重跑: {job_paths.manifest_path}")

        manifest = read_job_manifest(job_paths.manifest_path)
        loaded_settings = load_settings(
            settings_path=job_paths.settings_path,
            profile_name=effective_profile or str(manifest.get("profile") or ""),
            project_root=root,
        )
        apply_model_overrides(
            loaded_settings,
            ModelOverrides(
                llm_model=request.model or frontend_settings.model or None,
                llm_reasoning_effort=request.reasoning_effort or frontend_settings.reasoning_effort or None,
                ocr_backend=request.ocr_backend or frontend_settings.ocr_backend or None,
                ocr_model=request.ocr_model or frontend_settings.ocr_model or None,
                ocr_reasoning_effort=request.ocr_reasoning_effort or frontend_settings.ocr_reasoning_effort or None,
            ),
        )
        raw_stages = loaded_settings.settings.pipeline.stages if loaded_settings.settings.pipeline else []
        stages = resolve_rerun_stages(raw_stages, request.start_stage)
        logger = setup_logging(loaded_settings.settings.runtime.log_level)

        app.state.update_state(
            state_path,
            status="running",
            current_stage=stages[0],
            error_message="",
            output_path="",
        )
        with codex_lb_environment(frontend_settings):
            for stage_name in stages:
                app.state.update_state(
                    state_path,
                    status="running",
                    current_stage=stage_name,
                )
                current_backend = effective_backend if stage_name == "refine" else None
                exit_code = run_stage(stage_name, loaded_settings, logger, backend_override=current_backend)
                if exit_code != 0:
                    raise JobRunnerError(f"job 重跑失败: stage={stage_name} exit_code={exit_code}")

        output_path = stage_output_path(loaded_settings, stages[-1])
        if "export-markdown" in stages:
            output_dir = str(manifest.get("output_dir") or "").strip()
            video_source = str(manifest.get("video_source") or "").strip()
            if not output_dir or not video_source:
                raise JobRunnerError("job manifest 缺少 output_dir 或 video_source，无法复制最终输出。")
            _, copied_output_path = copy_final_output(
                job_paths,
                Path(output_dir).expanduser().resolve(),
                build_final_output_filename(
                    Path(video_source),
                    book_name=str(manifest.get("book_name") or "") or None,
                    chapter=str(manifest.get("chapter") or "") or None,
                ),
            )
            output_path = str(copied_output_path)

        app.state.update_state(
            state_path,
            status="success",
            current_stage="done",
            output_path=output_path,
        )
    except (ConfigLoadError, JobRunnerError, ValueError, OSError) as exc:
        app.state.update_state(
            state_path,
            status="failed",
            error_message=str(exc),
        )
    finally:
        app.state.active_jobs.discard(job_id)


def execute_batch_job(*, app: FastAPI, batch_id: str, payload: dict) -> None:
    state_path = app.state.batch_state_path(batch_id)
    root = app.state.project_root

    app.state.active_jobs.add(batch_id)
    try:
        request = BatchJobRequest.model_validate(payload)
        frontend_settings = load_frontend_settings(root)
        effective_profile = first_text(request.profile, frontend_settings.profile)
        effective_backend = first_text(request.backend, frontend_settings.backend)
        effective_book_name = first_text(request.book_name, frontend_settings.book_name)
        effective_chapter = first_text(request.chapter, frontend_settings.chapter)
        effective_glossary_file = first_text(request.glossary_file, frontend_settings.glossary_file)
        effective_remote_concurrency = request.remote_concurrency or frontend_settings.remote_concurrency
        model_overrides = ModelOverrides(
            llm_model=request.model or frontend_settings.model or None,
            llm_reasoning_effort=request.reasoning_effort or frontend_settings.reasoning_effort or None,
            ocr_backend=request.ocr_backend or frontend_settings.ocr_backend or None,
            ocr_model=request.ocr_model or frontend_settings.ocr_model or None,
            ocr_reasoning_effort=request.ocr_reasoning_effort or frontend_settings.ocr_reasoning_effort or None,
        )
        base_loaded_settings = load_settings(
            settings_path=request.config,
            profile_name=effective_profile,
            project_root=root,
        )
        job_specs, failed_runtimes = load_batch_job_specs(
            base_loaded_settings=base_loaded_settings,
            manifest=request.manifest,
            videos_dir=request.videos_dir,
            reference_dir=request.reference_dir,
            shared_reference=request.shared_reference,
            output_dir=request.output_dir,
            book_name=effective_book_name,
            chapter=effective_chapter,
            glossary_file=effective_glossary_file,
        )
        runtimes = list(failed_runtimes)
        runtimes.extend(
            prepare_batch_jobs(
                project_root=root,
                base_loaded_settings=base_loaded_settings,
                job_specs=job_specs,
                model_overrides=model_overrides,
            )
        )

        app.state.update_state(
            state_path,
            status="running",
            current_stage="prepare-job",
            total=len(runtimes),
            items=[serialize_batch_runtime(item) for item in runtimes],
        )

        logger = setup_logging(base_loaded_settings.settings.runtime.log_level)
        with codex_lb_environment(frontend_settings):
            for stage_name in ("extract-audio", "transcribe", "prepare-reference", "refine", "export-markdown"):
                app.state.update_state(
                    state_path,
                    status="running",
                    current_stage=stage_name,
                    items=[serialize_batch_runtime(item) for item in runtimes],
                )
                from src.job_runner import run_batch_stage  # local import keeps surface small

                run_batch_stage(
                    stage_name=stage_name,
                    runtimes=runtimes,
                    project_root=root,
                    logger=logger,
                    remote_concurrency=effective_remote_concurrency,
                    backend_override=effective_backend,
                )

        success_count = sum(1 for item in runtimes if item.status == "success")
        failed_count = sum(1 for item in runtimes if item.status == "failed")
        summary = BatchRunSummary(
            batch_id=batch_id,
            total=len(runtimes),
            success=success_count,
            failed=failed_count,
            items=runtimes,
        )
        write_batch_summary(project_root=root, summary=summary)

        app.state.update_state(
            state_path,
            status="success" if failed_count == 0 else "failed",
            current_stage="done",
            output_path=str(build_batch_root(root, batch_id) / "summary.json"),
            total=summary.total,
            success=summary.success,
            failed=summary.failed,
            items=[serialize_batch_runtime(item) for item in runtimes],
        )
    except (ConfigLoadError, JobRunnerError, ValueError, OSError) as exc:
        app.state.update_state(
            state_path,
            status="failed",
            error_message=str(exc),
        )
    finally:
        app.state.active_jobs.discard(batch_id)


def execute_stage_run(*, app: FastAPI, run_id: str, stage_name: str, payload: dict) -> None:
    state_path = app.state.stage_run_state_path(run_id)
    root = app.state.project_root

    app.state.active_jobs.add(run_id)
    try:
        request = StageRunRequest.model_validate(payload)
        frontend_settings = load_frontend_settings(root)
        normalized_stage_name = normalize_stage_name(stage_name)
        effective_profile = first_text(request.profile, frontend_settings.profile)
        effective_backend = first_text(request.backend, frontend_settings.backend)
        loaded_settings = load_settings(
            settings_path=request.config,
            profile_name=effective_profile,
            project_root=root,
        )
        apply_model_overrides(
            loaded_settings,
            ModelOverrides(
                llm_model=request.model or frontend_settings.model or None,
                llm_reasoning_effort=request.reasoning_effort or frontend_settings.reasoning_effort or None,
                ocr_backend=request.ocr_backend or frontend_settings.ocr_backend or None,
                ocr_model=request.ocr_model or frontend_settings.ocr_model or None,
                ocr_reasoning_effort=request.ocr_reasoning_effort or frontend_settings.ocr_reasoning_effort or None,
            ),
        )
        logger = setup_logging(loaded_settings.settings.runtime.log_level)
        app.state.update_state(
            state_path,
            status="running",
            current_stage=normalized_stage_name,
        )
        with codex_lb_environment(frontend_settings):
            exit_code = run_stage(
                normalized_stage_name,
                loaded_settings,
                logger,
                backend_override=effective_backend,
            )
        if exit_code != 0:
            raise JobRunnerError(f"stage 运行失败: stage={normalized_stage_name} exit_code={exit_code}")

        app.state.update_state(
            state_path,
            status="success",
            current_stage=normalized_stage_name,
            output_path=stage_output_path(loaded_settings, normalized_stage_name),
        )
    except (ConfigLoadError, JobRunnerError, ValueError, OSError) as exc:
        app.state.update_state(
            state_path,
            status="failed",
            error_message=str(exc),
        )
    finally:
        app.state.active_jobs.discard(run_id)
