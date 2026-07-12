from __future__ import annotations

import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
import uvicorn

from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import create_batch_id, create_job_id, supported_reference_extensions, supported_video_extensions
from src.refine_utils import PromptLoadError, VALID_REFINEMENT_BACKENDS, load_markdown_assemble_prompt
from src.runtime_utils import normalize_stage_name
from src.web.artifacts import collect_job_artifacts, read_job_artifact
from src.web.downloads import (
    build_batch_result_archive,
    build_result_download,
    normalize_result_format,
    resolve_batch_item_result_path,
    resolve_job_result_path,
)
from src.web.fs_browser import list_fs_items, resolve_allowed_browse_path, resolve_parent_path
from src.web.frontend_settings import FrontendSettingsUpdate, frontend_settings_response, load_frontend_settings, save_frontend_settings
from src.web.models import BatchJobRequest, JobRerunRequest, SingleJobRequest, StageFileRunRequest, StageRunRequest
from src.web.stage_file_runs import (
    StageFileRunError,
    build_stage_input_destination,
    normalize_result_name,
    stage_input_slots,
    validate_stage_input_files,
)
from src.web.state_store import collect_state_items, create_initial_state, read_json_file, update_state, write_json_file
from src.web.tasks import (
    execute_batch_item_rerun,
    execute_batch_job,
    execute_job_rerun,
    execute_single_job,
    execute_stage_file_run,
    execute_stage_run,
    submit_task,
)
from src.web.uploads import (
    UploadKind,
    build_upload_destination,
    save_upload_request,
    upload_allowed_extensions,
    upload_group_path,
    upload_root,
)


JOB_INPUT_SUMMARY_KEYS = (
    "content_type",
    "video_source",
    "reference_source",
    "output_dir",
    "book_name",
    "chapter",
    "glossary_file",
)
BATCH_INPUT_SUMMARY_KEYS = (
    "content_type",
    "manifest",
    "videos_dir",
    "reference_dir",
    "shared_reference",
    "output_dir",
    "book_name",
    "chapter",
    "glossary_file",
)


def compact_input_summary(raw: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            summary[key] = text
    return summary


def single_job_input_summary(request: SingleJobRequest) -> dict[str, str]:
    return compact_input_summary(
        {
            "video_source": request.video,
            "reference_source": request.reference,
            "output_dir": request.output_dir,
            "content_type": request.content_type,
            "book_name": request.book_name,
            "chapter": request.chapter,
            "glossary_file": request.glossary_file,
        },
        JOB_INPUT_SUMMARY_KEYS,
    )


def batch_job_input_summary(request: BatchJobRequest) -> dict[str, str]:
    return compact_input_summary(request.model_dump(), BATCH_INPUT_SUMMARY_KEYS)


def enrich_state_input_summary(project_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("input_summary"):
        return state

    kind = str(state.get("kind") or "")
    identifier = str(state.get("id") or "").strip()
    if kind != "job" or not identifier:
        return state

    manifest_path = project_root / "data/jobs" / identifier / "manifest.json"
    if not manifest_path.exists():
        return state

    manifest = read_json_file(manifest_path)
    summary = compact_input_summary(manifest, JOB_INPUT_SUMMARY_KEYS)
    if not summary:
        return state

    enriched = dict(state)
    enriched["input_summary"] = summary
    return enriched


def find_batch_state_item(state: dict[str, Any], item_job_id: str) -> dict[str, Any] | None:
    for raw_item in state.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        if str(raw_item.get("job_id") or "") == item_job_id:
            return raw_item
    return None


def attachment_headers(filename: str) -> dict[str, str]:
    quoted = quote(filename)
    return {"Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted}'}


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
    app.state.execute_job_rerun = execute_job_rerun
    app.state.execute_batch_job = execute_batch_job
    app.state.execute_batch_item_rerun = execute_batch_item_rerun
    app.state.execute_stage_file_run = execute_stage_file_run
    app.state.execute_stage_run = execute_stage_run
    
    # Active jobs in-memory tracker
    app.state.active_jobs = set()

    def reconcile_state(state: dict) -> dict:
        """修正服务重启后仍停留在运行态的任务，并补充列表展示需要的输入摘要。"""
        if state.get("status") in ("running", "pending"):
            job_id = state.get("id")
            kind = state.get("kind", "job")
            if job_id not in app.state.active_jobs:
                state["status"] = "failed"
                state["error_message"] = "任务已意外中断或服务重启"
                if kind == "job":
                    path = app.state.job_state_path(job_id)
                elif kind == "batch":
                    path = app.state.batch_state_path(job_id)
                else:  # stage-run
                    path = app.state.stage_run_state_path(job_id)
                app.state.update_state(path, status="failed", error_message="任务已意外中断或服务重启")
        return enrich_state_input_summary(root, state)

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
            "default_backend": loaded_settings.settings.llm.backends[0] if loaded_settings.settings.llm.backends else "",
            "default_ocr_backend": loaded_settings.settings.reference.ai_ocr_backend,
            "active_profile": loaded_settings.active_profile_name,
            "video_extensions": sorted(supported_video_extensions(loaded_settings)),
            "reference_extensions": list(supported_reference_extensions()),
            "default_output_dir": str(loaded_settings.path_for("final_dir")),
            "upload_dir": str(upload_root(root)),
            "content_types": ["book_club", "conversation"],
        }

    @app.get("/api/refine-default-instruction")
    async def get_refine_default_instruction(
        content_type: Literal["book_club", "conversation"] = Query(default="book_club"),
    ) -> dict[str, str]:
        try:
            loaded_settings = load_settings(project_root=root)
            prompt_text = load_markdown_assemble_prompt(
                loaded_settings,
                content_type=content_type if content_type == "conversation" else None,
            )
        except (ConfigLoadError, PromptLoadError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"prompt": prompt_text}

    @app.get("/api/frontend-settings")
    async def get_frontend_settings() -> dict[str, object]:
        return frontend_settings_response(root)

    @app.put("/api/frontend-settings")
    async def put_frontend_settings(request: FrontendSettingsUpdate) -> dict[str, object]:
        save_frontend_settings(root, request)
        return frontend_settings_response(root)

    @app.get("/api/fs/list")
    async def list_fs_entries(
        path: str | None = None,
        type: Literal["file", "dir", "all"] = Query(default="all"),
        show_hidden: bool = False,
    ) -> dict[str, object]:
        current_path, allow_roots = resolve_allowed_browse_path(root, path)
        return {
            "current_path": str(current_path),
            "parent_path": resolve_parent_path(current_path, allow_roots),
            "items": list_fs_items(current_path, item_type=type, show_hidden=show_hidden),
        }

    @app.post("/api/uploads")
    async def post_upload(
        request: Request,
        kind: UploadKind = Query(...),
        filename: str = Query(...),
        group_id: str | None = None,
        relative_path: str | None = None,
    ) -> dict[str, object]:
        try:
            loaded_settings = load_settings(project_root=root)
        except ConfigLoadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        destination = build_upload_destination(
            project_root=root,
            kind=kind,
            filename=filename,
            allowed_extensions=upload_allowed_extensions(kind, loaded_settings),
            group_id=group_id,
            relative_path=relative_path,
        )
        size = await save_upload_request(request, destination)
        return {
            "kind": kind,
            "name": destination.name,
            "path": str(destination),
            "directory": str(upload_group_path(destination, group_id, relative_path)),
            "size": size,
        }

    @app.get("/api/jobs")
    async def list_jobs() -> dict[str, list[dict]]:
        items = collect_state_items(root / "data/jobs")
        return {"items": [reconcile_state(item) for item in items]}

    @app.get("/api/jobs/{job_id}")
    async def get_job_status(job_id: str) -> dict:
        state_path = app.state.job_state_path(job_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        state = read_json_file(state_path)
        return reconcile_state(state)

    @app.get("/api/jobs/{job_id}/artifacts")
    async def get_job_artifacts(job_id: str) -> dict[str, list[dict[str, object]]]:
        state_path = app.state.job_state_path(job_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        return {"items": collect_job_artifacts(root, job_id)}

    @app.get("/api/jobs/{job_id}/artifacts/{artifact_id}")
    async def get_job_artifact(job_id: str, artifact_id: str) -> dict[str, object]:
        state_path = app.state.job_state_path(job_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        try:
            artifact = read_job_artifact(root, job_id, artifact_id)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"读取产物失败: {exc}") from exc
        if artifact is None:
            raise HTTPException(status_code=404, detail=f"产物不存在: {artifact_id}")
        return artifact

    @app.get("/api/jobs/{job_id}/result")
    async def download_job_result(job_id: str, result_format: str = Query("markdown", alias="format")) -> Response:
        state_path = app.state.job_state_path(job_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        state = reconcile_state(read_json_file(state_path))
        try:
            normalized_format = normalize_result_format(result_format)
            result_path = resolve_job_result_path(root, state)
            download = build_result_download(result_path, normalized_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"读取任务结果失败: {exc}") from exc
        if download.path is not None:
            return FileResponse(download.path, filename=download.filename, media_type=download.media_type)
        return Response(
            content=download.content or b"",
            media_type=download.media_type,
            headers=attachment_headers(download.filename),
        )

    @app.post("/api/jobs", status_code=202)
    async def post_job(request: SingleJobRequest) -> dict[str, str]:
        job_id = create_job_id()
        app.state.active_jobs.add(job_id)
        state = create_initial_state(job_id, "job")
        state["input_summary"] = single_job_input_summary(request)
        write_json_file(app.state.job_state_path(job_id), state)
        submit_task(
            app,
            app.state.execute_single_job,
            app=app,
            job_id=job_id,
            payload=request.model_dump(),
        )
        return {"job_id": job_id}

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str) -> dict[str, bool]:
        if job_id in app.state.active_jobs:
            raise HTTPException(status_code=400, detail="不能删除正在运行的任务")
        job_dir = root / "data/jobs" / job_id
        if not job_dir.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        try:
            shutil.rmtree(job_dir)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"无法删除任务目录: {exc}")
        return {"success": True}

    @app.post("/api/jobs/{job_id}/rerun", status_code=202)
    async def post_job_rerun(job_id: str, request: JobRerunRequest) -> dict[str, str]:
        state_path = app.state.job_state_path(job_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
        if job_id in app.state.active_jobs:
            raise HTTPException(status_code=400, detail="不能重跑正在运行的任务")
        app.state.active_jobs.add(job_id)
        submit_task(
            app,
            app.state.execute_job_rerun,
            app=app,
            job_id=job_id,
            payload=request.model_dump(),
        )
        return {"job_id": job_id}

    @app.post("/api/batch-jobs", status_code=202)
    async def post_batch_jobs(request: BatchJobRequest) -> dict[str, str]:
        batch_id = create_batch_id()
        app.state.active_jobs.add(batch_id)
        state = create_initial_state(batch_id, "batch")
        state["input_summary"] = batch_job_input_summary(request)
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
        state = read_json_file(state_path)
        return reconcile_state(state)

    @app.get("/api/batches/{batch_id}/result")
    async def download_batch_result(batch_id: str, result_format: str = Query("markdown", alias="format")) -> Response:
        state_path = app.state.batch_state_path(batch_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"batch 不存在: {batch_id}")
        state = reconcile_state(read_json_file(state_path))
        try:
            normalized_format = normalize_result_format(result_format)
            archive = build_batch_result_archive(root, batch_id, state, normalized_format)
            archive_filename = (
                f"{batch_id}-results.zip"
                if normalized_format == "markdown"
                else f"{batch_id}-results-{normalized_format}.zip"
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"打包批量结果失败: {exc}") from exc
        return Response(
            content=archive,
            media_type="application/zip",
            headers=attachment_headers(archive_filename),
        )

    @app.get("/api/batches/{batch_id}/items/{item_job_id}/result")
    async def download_batch_item_result(
        batch_id: str,
        item_job_id: str,
        result_format: str = Query("markdown", alias="format"),
    ) -> Response:
        state_path = app.state.batch_state_path(batch_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"batch 不存在: {batch_id}")
        state = reconcile_state(read_json_file(state_path))
        try:
            normalized_format = normalize_result_format(result_format)
            result_path = resolve_batch_item_result_path(root, state, item_job_id)
            download = build_result_download(result_path, normalized_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"读取子任务结果失败: {exc}") from exc
        if download.path is not None:
            return FileResponse(download.path, filename=download.filename, media_type=download.media_type)
        return Response(
            content=download.content or b"",
            media_type=download.media_type,
            headers=attachment_headers(download.filename),
        )

    @app.post("/api/batches/{batch_id}/items/{item_job_id}/rerun", status_code=202)
    async def post_batch_item_rerun(batch_id: str, item_job_id: str, request: JobRerunRequest) -> dict[str, str]:
        state_path = app.state.batch_state_path(batch_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"batch 不存在: {batch_id}")

        # 批量任务和子任务重跑都会写同一个 batch state 文件，必须串行化避免状态互相覆盖。
        if batch_id in app.state.active_jobs:
            raise HTTPException(status_code=400, detail="不能在批量任务运行中重跑子任务")
        if item_job_id in app.state.active_jobs:
            raise HTTPException(status_code=400, detail="不能重跑正在运行的子任务")

        state = reconcile_state(read_json_file(state_path))
        item = find_batch_state_item(state, item_job_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"批量子任务不存在: {item_job_id}")
        if not str(item.get("job_id") or "").strip():
            raise HTTPException(status_code=400, detail="该批量子任务缺少 job_id，无法重跑")

        item_status = str(item.get("status") or "")
        if item_status not in {"success", "failed"}:
            raise HTTPException(status_code=400, detail="只能重跑已成功或已失败的批量子任务")

        app.state.active_jobs.add(batch_id)
        app.state.active_jobs.add(item_job_id)
        submit_task(
            app,
            app.state.execute_batch_item_rerun,
            app=app,
            batch_id=batch_id,
            item_job_id=item_job_id,
            payload=request.model_dump(),
        )
        return {"batch_id": batch_id, "job_id": item_job_id}

    @app.get("/api/batches")
    async def list_batches() -> dict[str, list[dict]]:
        items = collect_state_items(root / "data/jobs/batches")
        return {"items": [reconcile_state(item) for item in items]}

    @app.delete("/api/batches/{batch_id}")
    async def delete_batch(batch_id: str) -> dict[str, bool]:
        if batch_id in app.state.active_jobs:
            raise HTTPException(status_code=400, detail="不能删除正在运行的批量任务")
        batch_dir = root / "data/jobs/batches" / batch_id
        if not batch_dir.exists():
            raise HTTPException(status_code=404, detail=f"batch 不存在: {batch_id}")
        try:
            shutil.rmtree(batch_dir)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"无法删除批量任务目录: {exc}")
        return {"success": True}

    @app.get("/api/stages/{stage_name}/file-contract")
    async def get_stage_file_contract(stage_name: str) -> dict[str, object]:
        try:
            loaded_settings = load_settings(project_root=root)
            normalized_stage_name = normalize_stage_name(stage_name)
            slots = stage_input_slots(normalized_stage_name, loaded_settings)
        except (ConfigLoadError, StageFileRunError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "stage_name": normalized_stage_name,
            "input_slots": [
                {
                    "key": slot.key,
                    "label": slot.label,
                    "extensions": list(slot.extensions),
                }
                for slot in slots
            ],
            "default_result_name": f"{normalized_stage_name}-result",
        }

    @app.post("/api/stage-inputs/{stage_name}/{slot_key}")
    async def post_stage_input(
        stage_name: str,
        slot_key: str,
        request: Request,
        filename: str = Query(...),
    ) -> dict[str, object]:
        try:
            loaded_settings = load_settings(project_root=root)
            normalized_stage_name = normalize_stage_name(stage_name)
            destination = build_stage_input_destination(
                project_root=root,
                stage_name=normalized_stage_name,
                slot_key=slot_key,
                filename=filename,
                loaded_settings=loaded_settings,
            )
        except (ConfigLoadError, StageFileRunError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        size = await save_upload_request(request, destination)
        return {
            "stage_name": normalized_stage_name,
            "slot": slot_key,
            "name": destination.name,
            "path": str(destination),
            "size": size,
        }

    @app.post("/api/stages/{stage_name}/file-run", status_code=202)
    async def post_stage_file_run(stage_name: str, request: StageFileRunRequest) -> dict[str, str]:
        try:
            frontend_settings = load_frontend_settings(root)
            normalized_stage_name = normalize_stage_name(stage_name)
            effective_profile = (request.profile or "").strip() or frontend_settings.profile
            loaded_settings = load_settings(
                settings_path=request.config,
                profile_name=effective_profile,
                project_root=root,
            )
            staged_inputs = validate_stage_input_files(
                project_root=root,
                stage_name=normalized_stage_name,
                input_files=request.input_files,
                loaded_settings=loaded_settings,
            )
            result_name = normalize_result_name(request.result_name)
        except (ConfigLoadError, StageFileRunError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        run_id = uuid.uuid4().hex[:12]
        app.state.active_jobs.add(run_id)
        state = create_initial_state(run_id, "stage-run")
        state["current_stage"] = normalized_stage_name
        state["run_mode"] = "file"
        state["download_name"] = f"{result_name}.zip"
        state["input_summary"] = {slot_key: path.name for slot_key, path in staged_inputs.items()}
        write_json_file(app.state.stage_run_state_path(run_id), state)
        submit_task(
            app,
            app.state.execute_stage_file_run,
            app=app,
            run_id=run_id,
            stage_name=normalized_stage_name,
            payload=request.model_dump(),
        )
        return {"run_id": run_id}

    @app.post("/api/stages/{stage_name}", status_code=202)
    async def post_stage_run(stage_name: str, request: StageRunRequest) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]
        app.state.active_jobs.add(run_id)
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
        state = read_json_file(state_path)
        return reconcile_state(state)

    @app.get("/api/stage-runs/{run_id}/result")
    async def download_stage_file_result(run_id: str) -> FileResponse:
        state_path = app.state.stage_run_state_path(run_id)
        if not state_path.exists():
            raise HTTPException(status_code=404, detail=f"stage run 不存在: {run_id}")
        state = reconcile_state(read_json_file(state_path))
        if state.get("run_mode") != "file":
            raise HTTPException(status_code=400, detail="只有本机文件模式的单阶段运行支持结果下载。")
        if state.get("status") != "success":
            raise HTTPException(status_code=400, detail="阶段任务尚未成功完成，暂无可下载结果。")

        result_root = (root / "data/jobs/stage-runs" / run_id / "result").resolve()
        result_path = Path(str(state.get("output_path") or "")).resolve()
        try:
            result_path.relative_to(result_root)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="阶段结果路径无效。") from exc
        if not result_path.is_file():
            raise HTTPException(status_code=404, detail="阶段结果归档不存在。")
        download_name = str(state.get("download_name") or result_path.name)
        return FileResponse(result_path, filename=download_name, media_type="application/zip")

    @app.get("/api/stage-runs")
    async def list_stage_runs() -> dict[str, list[dict]]:
        items = collect_state_items(root / "data/jobs/stage-runs")
        return {"items": [reconcile_state(item) for item in items]}

    @app.delete("/api/stage-runs/{run_id}")
    async def delete_stage_run(run_id: str) -> dict[str, bool]:
        if run_id in app.state.active_jobs:
            raise HTTPException(status_code=400, detail="不能删除正在运行的阶段任务")
        run_dir = root / "data/jobs/stage-runs" / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail=f"stage run 不存在: {run_id}")
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"无法删除阶段任务目录: {exc}")
        return {"success": True}

    return app


app = create_app()


def main() -> None:
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
