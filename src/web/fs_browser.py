from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import HTTPException


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_allowed_browse_path(project_root: Path, requested_path: str | None) -> tuple[Path, list[Path]]:
    allow_roots = [Path.home().resolve(), project_root.resolve()]
    candidate = Path(requested_path).expanduser().resolve() if requested_path else Path.home().resolve()
    if not any(is_within_root(candidate, allowed_root) for allowed_root in allow_roots):
        raise HTTPException(status_code=403, detail=f"禁止访问路径: {candidate}")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {candidate}")
    return candidate, allow_roots


def list_fs_items(
    current_path: Path,
    *,
    item_type: Literal["file", "dir", "all"],
    show_hidden: bool,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for child in sorted(current_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if not show_hidden and child.name.startswith("."):
            continue
        if item_type == "file" and not child.is_file():
            continue
        if item_type == "dir" and not child.is_dir():
            continue
        items.append(
            {
                "name": child.name,
                "path": str(child.resolve()),
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 0,
            }
        )
    return items


def resolve_parent_path(current_path: Path, allow_roots: list[Path]) -> str | None:
    parent = current_path.parent.resolve()
    if any(is_within_root(parent, allowed_root) for allowed_root in allow_roots):
        return str(parent)
    return None
