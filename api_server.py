from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
import uvicorn

from scripts.run_pipeline import run_stage
from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import (
    BatchRunSummary,
    JobRunnerError,
    build_batch_root,
    build_final_output_filename,
    build_job_paths,
    copy_final_output,
    create_batch_id,
    create_job_id,
    load_batch_job_specs,
    prepare_batch_jobs,
    prepare_job_inputs,
    serialize_batch_runtime,
    write_batch_summary,
    write_job_manifest,
    write_job_settings,
)
from src.runtime_utils import normalize_stage_name, setup_logging
from src.refine_utils import VALID_REFINEMENT_BACKENDS


class SingleJobRequest(BaseModel):
    video: str
    reference: str
    output_dir: str
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_cli", "gemini_cli", "both"] | None = None
    book_name: str | None = None
    chapter: str | None = None
    glossary_file: str | None = None


class BatchJobRequest(BaseModel):
    manifest: str | None = None
    videos_dir: str | None = None
    reference_dir: str | None = None
    shared_reference: str | None = None
    output_dir: str | None = None
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_cli", "gemini_cli", "both"] | None = None
    glossary_file: str | None = None
    remote_concurrency: int = Field(default=2, ge=1)
    book_name: str | None = None
    chapter: str | None = None


class StageRunRequest(BaseModel):
    config: str | None = None
    profile: str | None = None
    backend: Literal["codex_cli", "gemini_cli", "both"] | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"无法读取文件: {path} | {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"JSON 解析失败: {path} | {exc}") from exc


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


def create_initial_state(identifier: str, kind: str) -> dict:
    timestamp = now_iso()
    return {
        "id": identifier,
        "kind": kind,
        "status": "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "current_stage": "",
        "error_message": "",
        "output_path": "",
    }


def submit_task(fastapi_app: FastAPI, func, **kwargs) -> None:
    if fastapi_app.state.run_tasks_inline:
        func(**kwargs)
        return
    fastapi_app.state.executor.submit(func, **kwargs)


def collect_state_items(base_dir: Path) -> list[dict]:
    if not base_dir.exists():
        return []

    items: list[dict] = []
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name in {"batches", "stage-runs"}:
            continue
        state_path = child / "state.json"
        if state_path.exists():
            items.append(read_json_file(state_path))
    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return items


def resolve_allowed_browse_path(root: Path, requested_path: str | None) -> tuple[Path, list[Path]]:
    allow_roots = [Path.home().resolve(), root.resolve()]
    candidate = Path(requested_path).expanduser().resolve() if requested_path else Path.home().resolve()
    if not any(is_within_root(candidate, allowed_root) for allowed_root in allow_roots):
        raise HTTPException(status_code=403, detail=f"禁止访问路径: {candidate}")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {candidate}")
    return candidate, allow_roots


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


def create_app(*, project_root: Path | None = None, run_tasks_inline: bool = False) -> FastAPI:
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            app.state.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="transcript-pipeline API", lifespan=lifespan)
    app.state.project_root = root
    app.state.run_tasks_inline = run_tasks_inline
    app.state.executor = ThreadPoolExecutor(max_workers=4)
    app.state.job_state_path = lambda job_id: root / "data/jobs" / job_id / "state.json"
    app.state.batch_state_path = lambda batch_id: root / "data/jobs/batches" / batch_id / "state.json"
    app.state.stage_run_state_path = lambda run_id: root / "data/jobs/stage-runs" / run_id / "state.json"
    app.state.update_state = lambda path, **changes: update_state(path, **changes)
    app.state.execute_single_job = execute_single_job
    app.state.execute_batch_job = execute_batch_job
    app.state.execute_stage_run = execute_stage_run

    @app.get("/api/config")
    async def get_config() -> dict[str, object]:
        try:
            loaded_settings = load_settings(project_root=root)
        except ConfigLoadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {
            "profiles": sorted(loaded_settings.settings.profiles.keys()),
            "backends": [*VALID_REFINEMENT_BACKENDS, "both"],
            "configured_backends": list(loaded_settings.settings.llm.backends),
            "active_profile": loaded_settings.active_profile_name,
        }

    @app.get("/api/fs/list")
    async def list_fs_entries(
        path: str | None = None,
        type: Literal["file", "dir", "all"] = Query(default="all"),
        show_hidden: bool = False,
    ) -> dict[str, object]:
        current_path, allow_roots = resolve_allowed_browse_path(root, path)
        items: list[dict[str, object]] = []
        for child in sorted(current_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if not show_hidden and child.name.startswith("."):
                continue
            if type == "file" and not child.is_file():
                continue
            if type == "dir" and not child.is_dir():
                continue
            items.append(
                {
                    "name": child.name,
                    "path": str(child.resolve()),
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0,
                }
            )

        parent = current_path.parent.resolve()
        parent_path = str(parent) if any(is_within_root(parent, allowed_root) for allowed_root in allow_roots) else None
        return {
            "current_path": str(current_path),
            "parent_path": parent_path,
            "items": items,
        }

    @app.get("/api/jobs")
    async def list_jobs() -> dict[str, list[dict]]:
        return {"items": collect_state_items(root / "data/jobs")}

    @app.get("/api/jobs/{job_id}")
    async def get_job_status(job_id: str) -> dict:
        state_path = app.state.job_state_path(job_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        return read_json_file(state_path)

    @app.post("/api/jobs", status_code=202)
    async def post_job(request: SingleJobRequest) -> dict[str, str]:
        job_id = create_job_id()
        write_json_file(app.state.job_state_path(job_id), create_initial_state(job_id, "job"))
        submit_task(
            app,
            app.state.execute_single_job,
            app=app,
            job_id=job_id,
            payload=request.model_dump(),
        )
        return {"job_id": job_id}

    @app.post("/api/batch-jobs", status_code=202)
    async def post_batch_jobs(request: BatchJobRequest) -> dict[str, str]:
        batch_id = create_batch_id()
        state = create_initial_state(batch_id, "batch")
        state["items"] = []
        write_json_file(app.state.batch_state_path(batch_id), state)
        submit_task(
            app,
            app.state.execute_batch_job,
            app=app,
            batch_id=batch_id,
            payload=request.model_dump(),
        )
        return {"batch_id": batch_id}

    @app.get("/api/batches/{batch_id}")
    async def get_batch_status(batch_id: str) -> dict:
        state_path = app.state.batch_state_path(batch_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"batch 不存在: {batch_id}")
        return read_json_file(state_path)

    @app.post("/api/stages/{stage_name}", status_code=202)
    async def post_stage_run(stage_name: str, request: StageRunRequest) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]
        state = create_initial_state(run_id, "stage-run")
        state["current_stage"] = normalize_stage_name(stage_name)
        write_json_file(app.state.stage_run_state_path(run_id), state)
        submit_task(
            app,
            app.state.execute_stage_run,
            app=app,
            run_id=run_id,
            stage_name=stage_name,
            payload=request.model_dump(),
        )
        return {"run_id": run_id}

    @app.get("/api/stage-runs/{run_id}")
    async def get_stage_run_status(run_id: str) -> dict:
        state_path = app.state.stage_run_state_path(run_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"stage run 不存在: {run_id}")
        return read_json_file(state_path)

    return app


def update_state(path: Path, **changes) -> dict:
    state = read_json_file(path) if path.exists() else create_initial_state(path.parent.name, "job")
    state.update(changes)
    state["updated_at"] = now_iso()
    write_json_file(path, state)
    return state


app = create_app()


def main() -> None:
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
