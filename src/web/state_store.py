from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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


def update_state(path: Path, **changes) -> dict:
    state = read_json_file(path) if path.exists() else create_initial_state(path.parent.name, "job")
    state.update(changes)
    state["updated_at"] = now_iso()
    write_json_file(path, state)
    return state


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
