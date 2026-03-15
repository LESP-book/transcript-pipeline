from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
import uvicorn

from src.config_loader import ConfigLoadError, load_settings
from src.job_runner import create_batch_id, create_job_id
from src.refine_utils import VALID_REFINEMENT_BACKENDS
from src.runtime_utils import normalize_stage_name
from src.web.fs_browser import list_fs_items, resolve_allowed_browse_path, resolve_parent_path
from src.web.models import BatchJobRequest, SingleJobRequest, StageRunRequest
from src.web.state_store import collect_state_items, create_initial_state, read_json_file, update_state, write_json_file
from src.web.tasks import execute_batch_job, execute_single_job, execute_stage_run, submit_task


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
        return {
            "current_path": str(current_path),
            "parent_path": resolve_parent_path(current_path, allow_roots),
            "items": list_fs_items(current_path, item_type=type, show_hidden=show_hidden),
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


app = create_app()


def main() -> None:
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
