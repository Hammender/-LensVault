"""有界插件进程通信、停止信号和错误脱敏。"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

MAX_STDOUT_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 4 * 1024 * 1024
STREAM_QUEUE_SIZE = 4


class PluginAborted(RuntimeError):
    """用户停止或试采截止，应结束整个任务。"""


def safe_error(message: str, secrets: list[str], limit: int = 1000) -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            message = message.replace(secret, "[已隐藏凭据]")
    return message[-limit:]


def check_abort(abort_event: threading.Event | None, deadline: float | None) -> None:
    if abort_event is not None and abort_event.is_set():
        raise PluginAborted("采集已停止")
    if deadline is not None and time.monotonic() >= deadline:
        raise PluginAborted("试采超时，请缩小范围后重试")


def kill_process_group(process: subprocess.Popen) -> None:
    # 父进程已退出时，仍需回收持有管道的后代进程。
    if os.name == "nt":
        if process.poll() is None:
            try:
                result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                        capture_output=True, timeout=5, check=False)
                if result.returncode and process.poll() is None:
                    process.kill()
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


class _ProcessIO:
    def __init__(self, command: list[str], payload: str, folder: Path, stream: bool):
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=folder, start_new_session=os.name != "nt",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self.lines: queue.Queue[bytes | None] = queue.Queue(maxsize=STREAM_QUEUE_SIZE)
        self.closed = threading.Event()
        self.stdout_done = threading.Event()
        self.stderr_done = threading.Event()
        self.error: Exception | None = None
        self.stdout = b""
        self.stderr = bytearray()
        self.threads = [
            threading.Thread(target=self._guard, args=(lambda: self._write(payload),), daemon=True),
            threading.Thread(target=self._guard, args=(lambda: self._read_stdout(stream),), daemon=True),
            threading.Thread(target=self._guard, args=(self._read_stderr,), daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def _guard(self, action) -> None:
        try:
            action()
        except Exception:
            # 不把原始通信异常中的请求内容交给接口或日志。
            self.error = self.error or RuntimeError("插件进程通信失败")

    def _write(self, payload: str) -> None:
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(payload.encode("utf-8"))
            self.process.stdin.close()
        except BrokenPipeError:
            # 由退出码和完整 stderr 报告提前退出，保留可脱敏的原因。
            pass

    def _put(self, line: bytes | None) -> None:
        while not self.closed.is_set():
            try:
                self.lines.put(line, timeout=0.05)
                return
            except queue.Full:
                pass

    def _read_stdout(self, stream: bool) -> None:
        assert self.process.stdout is not None
        try:
            if stream:
                while not self.closed.is_set():
                    line = self.process.stdout.readline(MAX_STDOUT_BYTES + 1)
                    if not line:
                        self._put(None)
                        return
                    if len(line) > MAX_STDOUT_BYTES:
                        self.error = RuntimeError("插件输出超过大小上限")
                        return
                    self._put(line)
            else:
                self.stdout = self.process.stdout.read(MAX_STDOUT_BYTES + 1)
                if len(self.stdout) > MAX_STDOUT_BYTES:
                    self.error = RuntimeError("插件输出超过大小上限")
        finally:
            self.stdout_done.set()

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        try:
            while chunk := self.process.stderr.read(64 * 1024):
                if len(self.stderr) + len(chunk) > MAX_STDERR_BYTES:
                    self.error = RuntimeError("插件错误输出超过大小上限")
                    self.stderr.clear()
                    return
                self.stderr.extend(chunk)
        finally:
            self.stderr_done.set()

    def check(self, abort_event, deadline) -> None:
        check_abort(abort_event, deadline)
        if self.error is not None:
            raise self.error

    def wait(self, abort_event, deadline, timeout: float, command) -> None:
        expires = time.monotonic() + timeout
        while True:
            self.check(abort_event, deadline)
            if self.process.poll() is not None and self.stdout_done.is_set() and self.stderr_done.is_set():
                return
            if time.monotonic() >= expires:
                raise subprocess.TimeoutExpired(command, timeout)
            self.closed.wait(0.05)

    def result_error(self, secrets: list[str]) -> None:
        if self.process.returncode:
            message = self.stderr.decode("utf-8", "replace") or "插件执行失败"
            raise RuntimeError(safe_error(message, secrets))

    def close(self) -> None:
        self.closed.set()
        kill_process_group(self.process)
        for thread in self.threads:
            thread.join(timeout=5)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None and not pipe.closed:
                try:
                    pipe.close()
                except (BrokenPipeError, OSError):
                    pass


class PluginRunner:
    def run_once(self, command, payload, folder, secrets, abort_event, timeout):
        io = _ProcessIO(command, payload, folder, False)
        try:
            io.wait(abort_event, None, timeout, command)
            io.result_error(secrets)
            try:
                return json.loads(io.stdout.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError("插件输出不是有效的 UTF-8 JSON") from exc
        finally:
            io.close()

    def stream(self, command, payload, folder, secrets, abort_event, idle_timeout, deadline):
        io = _ProcessIO(command, payload, folder, True)
        waiting_since = time.monotonic()
        try:
            while True:
                io.check(abort_event, deadline)
                try:
                    line = io.lines.get(timeout=0.05)
                except queue.Empty:
                    if time.monotonic() - waiting_since >= idle_timeout:
                        raise RuntimeError("插件执行失败或长时间没有输出")
                    continue
                if line is None:
                    break
                try:
                    page = json.loads(line.decode("utf-8"))
                except (UnicodeError, ValueError) as exc:
                    raise ValueError("插件输出不是有效的 UTF-8 JSON") from exc
                yield page
                waiting_since = time.monotonic()
            io.wait(abort_event, deadline, 10, command)
            io.result_error(secrets)
        finally:
            io.close()
