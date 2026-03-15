from __future__ import annotations

from pathlib import Path

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
from src.web.models import BatchJobRequest, SingleJobRequest, StageRunRequest


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


def execute_single_job(*, app: FastAPI, job_id: str, payload: dict) -> None:
    state_path = app.state.job_state_path(job_id)
    root = app.state.project_root

    try:
        request = SingleJobRequest.model_validate(payload)
        base_loaded_settings = load_settings(
            settings_path=request.config,
            profile_name=request.profile,
            project_root=root,
        )
        profile_name = request.profile or base_loaded_settings.active_profile_name
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
            glossary_file=request.glossary_file,
            book_name=request.book_name,
            chapter=request.chapter,
        )
        write_job_manifest(
            loaded_settings=base_loaded_settings,
            job_paths=job_paths,
            prepared_inputs=prepared_inputs,
            video_source=video_source,
            reference_source=request.reference,
            output_dir=output_dir,
            profile_name=profile_name,
            book_name=request.book_name,
            chapter=request.chapter,
            glossary_file=request.glossary_file,
        )

        job_loaded_settings = load_settings(
            settings_path=generated_settings_path,
            profile_name=profile_name,
            project_root=root,
        )
        logger = setup_logging(job_loaded_settings.settings.runtime.log_level)
        stages = [normalize_stage_name(stage_name) for stage_name in job_loaded_settings.settings.pipeline.stages]

        for stage_name in stages:
            app.state.update_state(
                state_path,
                status="running",
                current_stage=stage_name,
            )
            current_backend = request.backend if stage_name == "refine" else None
            exit_code = run_stage(stage_name, job_loaded_settings, logger, backend_override=current_backend)
            if exit_code != 0:
                raise JobRunnerError(f"job 主链失败: stage={stage_name} exit_code={exit_code}")

        _, copied_output_path = copy_final_output(
            job_paths,
            output_dir,
            build_final_output_filename(
                video_source,
                book_name=request.book_name,
                chapter=request.chapter,
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


def execute_batch_job(*, app: FastAPI, batch_id: str, payload: dict) -> None:
    state_path = app.state.batch_state_path(batch_id)
    root = app.state.project_root

    try:
        request = BatchJobRequest.model_validate(payload)
        base_loaded_settings = load_settings(
            settings_path=request.config,
            profile_name=request.profile,
            project_root=root,
        )
        job_specs, failed_runtimes = load_batch_job_specs(
            base_loaded_settings=base_loaded_settings,
            manifest=request.manifest,
            videos_dir=request.videos_dir,
            reference_dir=request.reference_dir,
            shared_reference=request.shared_reference,
            output_dir=request.output_dir,
            book_name=request.book_name,
            chapter=request.chapter,
            glossary_file=request.glossary_file,
        )
        runtimes = list(failed_runtimes)
        runtimes.extend(
            prepare_batch_jobs(
                project_root=root,
                base_loaded_settings=base_loaded_settings,
                job_specs=job_specs,
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
                remote_concurrency=request.remote_concurrency,
                backend_override=request.backend,
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


def execute_stage_run(*, app: FastAPI, run_id: str, stage_name: str, payload: dict) -> None:
    state_path = app.state.stage_run_state_path(run_id)
    root = app.state.project_root

    try:
        request = StageRunRequest.model_validate(payload)
        normalized_stage_name = normalize_stage_name(stage_name)
        loaded_settings = load_settings(
            settings_path=request.config,
            profile_name=request.profile,
            project_root=root,
        )
        logger = setup_logging(loaded_settings.settings.runtime.log_level)
        app.state.update_state(
            state_path,
            status="running",
            current_stage=normalized_stage_name,
        )
        exit_code = run_stage(
            normalized_stage_name,
            loaded_settings,
            logger,
            backend_override=request.backend,
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
