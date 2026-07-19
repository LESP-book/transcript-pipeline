from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger("transcript_pipeline")
TRACE_SCHEMA_VERSION = 1


def trace_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def create_trace_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"run-{timestamp}-{uuid.uuid4().hex}"


def safe_trace_component(value: str) -> str:
    normalized = re.sub(r"[^\w.\-]+", "_", value.strip(), flags=re.UNICODE).strip("._")
    return normalized or "unknown"


def endpoint_metadata(raw_url: str) -> dict[str, Any]:
    try:
        parsed = urlparse(raw_url)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        # 诊断元数据解析失败不能覆盖原始网络异常；异常 URL 也不原样落盘，避免带出查询参数。
        return {"scheme": "", "host": "", "port": None, "path": ""}
    return {
        "scheme": parsed.scheme,
        "host": host,
        "port": port,
        "path": parsed.path,
    }


def sanitized_proxy_environment() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    ):
        raw_value = os.environ.get(name, "").strip()
        if not raw_value:
            continue
        if name.lower() == "no_proxy":
            result[name] = raw_value
            continue
        try:
            parsed = urlparse(raw_value)
            host = parsed.hostname
            parsed_port = parsed.port
        except ValueError:
            result[name] = "configured"
            continue
        if not parsed.scheme or not host:
            result[name] = "configured"
            continue
        port = f":{parsed_port}" if parsed_port is not None else ""
        result[name] = f"{parsed.scheme}://{host}{port}"
    return result


def text_fingerprint(text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    return {
        "chars": len(text),
        "utf8_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def exception_metadata(exc: BaseException, *, category: str) -> dict[str, Any]:
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "recorded_at": trace_now_iso(),
        "category": category,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }


@dataclass(frozen=True)
class RequestTrace:
    directory: Path

    def path_for(self, filename: str) -> Path:
        return self.directory / filename

    def write_text(self, filename: str, content: str) -> bool:
        path = self.path_for(filename)
        pending_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.pending")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            pending_path.write_text(content, encoding="utf-8")
            pending_path.replace(path)
            return True
        except OSError as exc:
            # 诊断落盘是旁路能力；磁盘权限或空间问题必须显式告警，但不能把合法模型结果改判为失败。
            LOGGER.warning("请求诊断文本写入失败 | path=%s | %s", path, exc)
            return False
        finally:
            try:
                if pending_path.exists():
                    pending_path.unlink()
            except OSError as exc:
                LOGGER.warning("请求诊断临时文件清理失败 | path=%s | %s", pending_path, exc)

    def write_json(self, filename: str, payload: dict[str, Any]) -> bool:
        try:
            content = json.dumps(payload, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            # 诊断序列化同样属于旁路，必须告警而不能改变正常请求结果。
            LOGGER.warning("请求诊断 JSON 序列化失败 | path=%s | %s", self.path_for(filename), exc)
            return False
        return self.write_text(filename, content)

    def read_json(self, filename: str) -> dict[str, Any]:
        path = self.path_for(filename)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # 已损坏的诊断索引不应阻断正常校对，但 warning 会保留真实问题，避免静默伪装成功。
            LOGGER.warning("请求诊断 JSON 读取失败 | path=%s | %s", path, exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    def record_transport(self, record: dict[str, Any], *, raw_response: str) -> None:
        payload = self.read_json("transport.json")
        raw_transports = payload.get("transports", [])
        transports = list(raw_transports) if isinstance(raw_transports, list) else []
        sequence = len(transports) + 1
        transport_name = safe_trace_component(str(record.get("transport") or "unknown"))
        raw_filename = f"raw-response-{sequence:02d}-{transport_name}.txt"
        self.write_text(raw_filename, raw_response)
        self.write_text("raw-response.sse", raw_response)
        transports.append({**record, "sequence": sequence, "raw_response_file": raw_filename})
        self.write_json(
            "transport.json",
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "updated_at": trace_now_iso(),
                "transports": transports,
            },
        )


def build_refine_request_trace(
    logs_dir: Path,
    *,
    basename: str,
    backend: str,
    run_id: str,
    attempt: int,
) -> RequestTrace:
    directory = (
        logs_dir
        / "refine"
        / safe_trace_component(basename)
        / safe_trace_component(backend)
        / safe_trace_component(run_id)
        / f"attempt-{attempt:03d}"
    )
    return RequestTrace(directory)


def update_refine_diagnostics_summary(logs_dir: Path, entry: dict[str, Any]) -> None:
    root_trace = RequestTrace(logs_dir / "refine")
    payload = root_trace.read_json("diagnostics.json")
    raw_attempts = payload.get("attempts", [])
    attempts = list(raw_attempts) if isinstance(raw_attempts, list) else []
    entry_key = (
        str(entry.get("run_id") or ""),
        str(entry.get("file") or ""),
        str(entry.get("backend") or ""),
        int(entry.get("attempt") or 0),
    )
    replaced = False
    for index, current in enumerate(attempts):
        if not isinstance(current, dict):
            continue
        current_key = (
            str(current.get("run_id") or ""),
            str(current.get("file") or ""),
            str(current.get("backend") or ""),
            int(current.get("attempt") or 0),
        )
        if current_key == entry_key:
            attempts[index] = entry
            replaced = True
            break
    if not replaced:
        attempts.append(entry)
    root_trace.write_json(
        "diagnostics.json",
        {
            "schema_version": TRACE_SCHEMA_VERSION,
            "stage": "refine",
            "updated_at": trace_now_iso(),
            "attempts": attempts,
        },
    )
