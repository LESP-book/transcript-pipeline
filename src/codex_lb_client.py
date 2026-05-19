from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.schemas import CodexLBSettings


class CodexLBClientError(RuntimeError):
    """codex-lb API 调用失败。"""


@dataclass(frozen=True)
class CodexLBClient:
    settings: CodexLBSettings
    timeout_seconds: float | None = None

    @property
    def base_url(self) -> str:
        env_name = self.settings.base_url_env.strip()
        env_value = os.environ.get(env_name, "").strip() if env_name else ""
        base_url = env_value or self.settings.base_url.strip()
        if not base_url:
            raise CodexLBClientError("codex-lb base_url 为空，请检查 codex_lb.base_url 或 CODEX_LB_BASE_URL。")
        return base_url.rstrip("/")

    @property
    def api_key(self) -> str:
        env_name = self.settings.api_key_env.strip()
        api_key = os.environ.get(env_name, "").strip() if env_name else ""
        if not api_key:
            raise CodexLBClientError(f"缺少 codex-lb API Key 环境变量: {env_name or 'CODEX_LB_API_KEY'}")
        return api_key

    def responses_text(self, payload: dict[str, Any]) -> str:
        response_payload = self.post_json(self.settings.responses_path, payload, label="Responses API")
        return extract_response_text(response_payload)

    def responses_stream_text(self, payload: dict[str, Any]) -> str:
        return self.post_event_stream(self.settings.responses_path, payload, label="Responses API")

    def codex_responses_text(self, payload: dict[str, Any]) -> str:
        return self.post_event_stream(self.settings.codex_responses_path, payload, label="Codex Responses API")

    def upload_file(self, file_path: Path, *, use_case: str = "codex") -> str:
        try:
            file_bytes = file_path.read_bytes()
        except OSError as exc:
            raise CodexLBClientError(f"无法读取待上传文件: {file_path} | {exc}") from exc

        create_payload = {
            "file_name": file_path.name,
            "file_size": len(file_bytes),
            "use_case": use_case,
        }
        create_result = self.post_json(self.settings.files_create_path, create_payload, label="文件注册")
        file_id = create_result.get("file_id")
        upload_url = create_result.get("upload_url")
        if not isinstance(file_id, str) or not file_id:
            raise CodexLBClientError(f"文件注册响应缺少 file_id: {create_result}")
        if not isinstance(upload_url, str) or not upload_url:
            raise CodexLBClientError(f"文件注册响应缺少 upload_url: {create_result}")

        self.put_file_bytes(upload_url, file_bytes, label="文件直传")
        finalize_path = self.settings.files_finalize_path_template.format(file_id=file_id)
        finalize_result = self.post_json(finalize_path, {}, label="文件上传完成确认")
        status = finalize_result.get("status")
        if status != "success":
            raise CodexLBClientError(f"文件上传完成确认失败: file_id={file_id}, status={status}, payload={finalize_result}")
        return file_id

    def post_json(self, path: str, payload: dict[str, Any], *, label: str) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            endpoint_url(self.base_url, path),
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        return parse_json_response(
            read_http_response(
                request,
                label=label,
                timeout_seconds=self.timeout_seconds,
                use_curl_first=should_use_curl_first(self.base_url),
            ),
            label=label,
        )

    def post_event_stream(self, path: str, payload: dict[str, Any], *, label: str) -> str:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            endpoint_url(self.base_url, path),
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "User-Agent": "codex_cli_rs/0.130.0 transcript-pipeline",
            },
        )
        return extract_event_stream_text(
            read_http_response(
                request,
                label=label,
                timeout_seconds=self.timeout_seconds,
                use_curl_first=should_use_curl_first(self.base_url),
            )
        )

    def put_file_bytes(self, upload_url: str, file_bytes: bytes, *, label: str) -> None:
        request = Request(
            upload_url,
            data=file_bytes,
            method="PUT",
            headers={
                # Azure Blob SAS 上传需要这个头；该要求来自 Codex 官方文件上传实现。
                "x-ms-blob-type": "BlockBlob",
                "Content-Length": str(len(file_bytes)),
            },
        )
        read_http_response(
            request,
            label=label,
            timeout_seconds=self.timeout_seconds,
            use_curl_first=should_use_curl_first(upload_url),
        )


def endpoint_url(base_url: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def read_http_response(
    request: Request,
    *,
    label: str,
    timeout_seconds: float | None,
    use_curl_first: bool = False,
) -> str:
    if use_curl_first:
        return read_http_response_with_curl(request, label=label, timeout_seconds=timeout_seconds)

    try:
        if timeout_seconds is None:
            with urlopen(request) as response:
                return response.read().decode("utf-8", errors="replace")
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if should_retry_with_curl(exc.code, body):
            return read_http_response_with_curl(request, label=label, timeout_seconds=timeout_seconds)
        raise CodexLBClientError(f"{label} HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise CodexLBClientError(f"{label} 请求失败: {exc}") from exc
    except OSError as exc:
        raise CodexLBClientError(f"{label} 请求失败: {exc}") from exc


def should_retry_with_curl(status_code: int, body: str) -> bool:
    if status_code != 403 or shutil.which("curl") is None:
        return False
    normalized = body.lower()
    return (
        "browser_signature_banned" in normalized
        or "cloudflare" in normalized
        or "error code: 1010" in normalized
        or "your request was blocked" in normalized
    )


def should_use_curl_first(url: str) -> bool:
    if shutil.which("curl") is None:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host not in {"", "127.0.0.1", "localhost", "::1"} and not host.endswith(".local")


def read_http_response_with_curl(request: Request, *, label: str, timeout_seconds: float | None) -> str:
    # 用户的远程 codex-lb 反代域会用 Cloudflare 1010 拦截 Python urllib 的 TLS/客户端指纹；
    # curl 已验证可通过同一 API 入口和远程文件上传 URL，因此远程地址优先使用 curl，本地仍走 urllib。
    body_path: Path | None = None
    try:
        if request.data is not None:
            with tempfile.NamedTemporaryFile(delete=False) as body_file:
                body_file.write(request.data)
                body_path = Path(body_file.name)

        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--request",
            request.get_method(),
            "--config",
            "-",
            "--output",
            "-",
            "--write-out",
            "\n%{http_code}",
        ]
        if timeout_seconds is not None:
            command.extend(["--max-time", str(timeout_seconds)])
        if body_path is not None:
            command.extend(["--data-binary", f"@{body_path}"])
        command.append(request.full_url)

        completed = subprocess.run(
            command,
            input=build_curl_header_config(dict(request.header_items())),
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        if body_path is not None:
            try:
                body_path.unlink()
            except OSError:
                pass

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"curl exited with code {completed.returncode}"
        raise CodexLBClientError(f"{label} curl 请求失败: {detail}")

    response_text, status_text = split_curl_response(completed.stdout)
    try:
        status_code = int(status_text)
    except ValueError as exc:
        raise CodexLBClientError(f"{label} curl 状态码解析失败: {status_text}") from exc
    if status_code >= 400:
        raise CodexLBClientError(f"{label} HTTP {status_code}: {response_text}")
    return response_text


def build_curl_header_config(headers: dict[str, str]) -> str:
    lines = []
    for key, value in headers.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'header = "{key}: {escaped}"')
    return "\n".join(lines) + "\n"


def split_curl_response(stdout: str) -> tuple[str, str]:
    if "\n" not in stdout:
        raise CodexLBClientError("curl 响应缺少 HTTP 状态码。")
    return stdout.rsplit("\n", 1)


def parse_json_response(text: str, *, label: str) -> dict[str, Any]:
    if not text.strip():
        raise CodexLBClientError(f"{label} 返回为空。")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CodexLBClientError(f"{label} JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise CodexLBClientError(f"{label} JSON 顶层必须是对象。")
    return payload


def extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    if isinstance(output_text, list):
        parts = [item for item in output_text if isinstance(item, str) and item]
        if parts:
            return "".join(parts).strip()

    parts: list[str] = []
    output_items = payload.get("output")
    if isinstance(output_items, list):
        for item in output_items:
            if not isinstance(item, dict):
                continue
            collect_text_parts(item.get("content"), parts)
            collect_text_parts(item, parts)

    text = "".join(parts).strip()
    if not text:
        raise CodexLBClientError(f"Responses API 返回中未找到 output_text: {payload}")
    return text


def extract_event_stream_text(stream_text: str) -> str:
    parts: list[str] = []
    completed_text: str | None = None
    failed_payload: dict[str, Any] | None = None
    for block in iter_sse_blocks(stream_text):
        event_name, data_text = parse_sse_block(block)
        if not data_text or data_text == "[DONE]":
            continue
        try:
            payload = json.loads(data_text)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or event_name or "")
        if event_type in {"response.output_text.delta", "response.text.delta"}:
            delta = payload.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
            continue
        if event_type in {"response.failed", "response.incomplete"}:
            failed_payload = payload
            continue
        if event_type == "response.completed":
            response = payload.get("response")
            if isinstance(response, dict):
                output_text = response.get("output_text")
                if isinstance(output_text, str) and output_text.strip():
                    completed_text = output_text.strip()

    if failed_payload is not None:
        raise CodexLBClientError(f"Codex Responses API 返回失败事件: {failed_payload}")
    text = "".join(parts).strip() or (completed_text or "").strip()
    if text:
        return text
    raise CodexLBClientError("Codex Responses API 流中未找到 output_text。")


def iter_sse_blocks(stream_text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in stream_text.splitlines():
        line = raw_line.rstrip("\r")
        if line:
            current.append(line)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_sse_block(lines: list[str]) -> tuple[str | None, str]:
    event_name: str | None = None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
    return event_name, "\n".join(data_lines).strip()


def collect_text_parts(content: Any, parts: list[str]) -> None:
    if isinstance(content, str):
        parts.append(content)
        return
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            parts.append(text)
        return
    if isinstance(content, list):
        for item in content:
            collect_text_parts(item, parts)
