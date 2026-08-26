from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .contracts import AccessBlockedError, USER_AGENT


def _compat_module():
    import app.services.acquisition_adapters as package
    return package


class _RequestStartLimiter:
    def __init__(
        self,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval_seconds = max(0.0, float(interval_seconds))
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = max(0.0, self._next_start - self._clock())
            if delay:
                self._sleeper(delay)
            self._next_start = self._clock() + self.interval_seconds


def is_tls_transport_error(exc: Exception) -> bool:
    message = str(exc).upper()
    markers = (
        "ASN1",
        "CERTIFICATE_VERIFY_FAILED",
        "EOF",
        "NOT_ENOUGH_DATA",
        "SSL",
        "TLS",
        "UNEXPECTED_EOF_WHILE_READING",
        "WRONG_VERSION_NUMBER",
    )
    return any(marker in message for marker in markers)


def curl_request_bytes(
    url: str,
    accept: str,
    referer: str,
    timeout: float = 45,
    max_bytes: int | None = None,
    retries: int = 3,
    abort_on_access_block: bool = False,
    before_attempt: Callable[[], None] | None = None,
) -> tuple[bytes, str]:
    package = _compat_module()
    curl = package.shutil.which("curl.exe") or package.shutil.which("curl")
    if not curl:
        raise RuntimeError("系统未安装 curl，无法回退处理网站 TLS 异常")
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("下载地址缺少主机名")
    attempts = max(1, int(retries))
    request_timeout = max(1, int(timeout))
    retry_delay = 1
    temporary = tempfile.NamedTemporaryFile(prefix="pictureshow-curl-", suffix=".tmp", delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    command = [
        curl,
        "--ipv4",
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--retry",
        str(0 if abort_on_access_block else attempts - 1),
        "--retry-delay",
        str(retry_delay),
        "--retry-all-errors",
        "--connect-timeout",
        str(min(30, request_timeout)),
        "--max-time",
        str(request_timeout),
        "--user-agent",
        USER_AGENT,
        "--header",
        f"Accept: {accept}",
        "--referer",
        referer,
        "--output",
        str(temporary_path),
        "--write-out",
        "%{http_code}\n%{content_type}" if abort_on_access_block else "%{content_type}",
    ]
    try:
        command.append(url)
        process_timeout = (
            request_timeout + 10
            if abort_on_access_block
            else attempts * request_timeout + (attempts - 1) * retry_delay + 10
        )
        last_error: RuntimeError | None = None
        process_attempts = attempts if abort_on_access_block else 1
        for attempt in range(process_attempts):
            if before_attempt is not None:
                before_attempt()
            try:
                result = package.subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=process_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                last_error = RuntimeError(
                    f"请求 {parsed.hostname} 超时：最多尝试 {attempts} 次，每次 {request_timeout} 秒"
                )
                if attempt + 1 >= process_attempts:
                    raise last_error from exc
                if before_attempt is None:
                    package.time.sleep(retry_delay)
                continue
            output = result.stdout.strip()
            status_text, _, content_type = output.partition("\n") if abort_on_access_block else ("", "", output)
            status_code = int(status_text) if status_text.isdigit() else 0
            if status_code in {403, 429}:
                raise AccessBlockedError(url, status_code)
            if result.returncode != 0:
                last_error = RuntimeError(result.stderr.strip() or f"curl 下载失败（退出码 {result.returncode}）")
                if attempt + 1 < process_attempts:
                    if before_attempt is None:
                        package.time.sleep(retry_delay)
                    continue
                raise last_error
            size = temporary_path.stat().st_size
            if max_bytes is not None and size > max_bytes:
                raise ValueError("文件超过下载大小上限")
            return temporary_path.read_bytes(), content_type
        raise last_error or RuntimeError("curl 下载失败")
    finally:
        temporary_path.unlink(missing_ok=True)


def _request_bytes(
    url: str,
    accept: str,
    referer: str,
    timeout: float = 45,
    abort_on_access_block: bool = False,
    retries: int = 1,
    before_attempt: Callable[[], None] | None = None,
) -> tuple[bytes, str]:
    package = _compat_module()
    request = Request(url, headers={"Accept": accept, "Referer": referer, "User-Agent": USER_AGENT})
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        if before_attempt is not None:
            before_attempt()
        try:
            with package.urlopen(request, timeout=timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except HTTPError as exc:
            if abort_on_access_block and exc.code in {403, 429}:
                raise AccessBlockedError(url, exc.code) from exc
            if attempt + 1 >= attempts:
                raise
        except Exception as exc:
            if is_tls_transport_error(exc):
                return curl_request_bytes(
                    url,
                    accept,
                    referer,
                    timeout,
                    retries=attempts,
                    abort_on_access_block=abort_on_access_block,
                    before_attempt=before_attempt,
                )
            if attempt + 1 >= attempts:
                raise
        if before_attempt is None:
            package.time.sleep(1)
    raise RuntimeError("请求失败")


