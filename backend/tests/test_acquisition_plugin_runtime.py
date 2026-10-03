"""插件子进程的超时、输出边界和资源收尾回归测试。"""

import sys
import os
import threading
import time
from types import SimpleNamespace

import pytest

from app.services.acquisition_plugins.manager import PluginManager
from app.services.acquisition_plugins.runtime import PluginAborted


def test_slow_consumer_does_not_timeout_buffered_pages(tmp_path):
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    command = [sys.executable, "-c", "import sys; sys.stdin.read(); print('{}', flush=True); print('{}', flush=True)"]
    pages = manager._stream(command, "{}", tmp_path, [], None, 0.1, None)
    try:
        assert next(pages) == {}
        time.sleep(0.2)
        assert next(pages) == {}
        with pytest.raises(StopIteration):
            next(pages)
    finally:
        pages.close()


@pytest.mark.parametrize("stream", [False, True])
def test_error_redacts_long_credentials_before_truncation(tmp_path, stream):
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    secret = "cookie-" + "x" * 1200
    command = [sys.executable, "-c", f"import sys; sys.stdin.read(); sys.stderr.write({secret!r}); sys.exit(1)"]
    with pytest.raises(RuntimeError) as error:
        if stream:
            list(manager._stream(command, "{}", tmp_path, [secret], None, 5, None))
        else:
            manager._run_once(command, "{}", tmp_path, [secret], None, 5)
    assert "x" * 100 not in str(error.value)
    assert "已隐藏凭据" in str(error.value)


def test_stream_times_out_when_no_page_arrives(tmp_path):
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    command = [sys.executable, "-c", "import sys,time; sys.stdin.read(); time.sleep(30)"]
    with pytest.raises(RuntimeError, match="长时间"):
        list(manager._stream(command, "{}", tmp_path, [], None, 0.1, None))


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("output", ["stdout", "stderr"])
def test_output_limits_stop_process_without_partial_error(tmp_path, monkeypatch, stream, output):
    monkeypatch.setattr("app.services.acquisition_plugins.runtime.MAX_STDOUT_BYTES", 256)
    monkeypatch.setattr("app.services.acquisition_plugins.runtime.MAX_STDERR_BYTES", 256)
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    command = [sys.executable, "-c", f"import sys; sys.stdin.read(); sys.{output}.write('sensitive-'+'x'*500)"]
    with pytest.raises(RuntimeError, match="大小上限") as error:
        if stream:
            list(manager._stream(command, "{}", tmp_path, [], None, 5, None))
        else:
            manager._run_once(command, "{}", tmp_path, [], None, 5)
    assert "sensitive" not in str(error.value)


def test_full_queue_can_be_closed_and_process_reaped(tmp_path):
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    pid_file = tmp_path / "pid"
    command = [sys.executable, "-c", f"import os,sys,time; from pathlib import Path; sys.stdin.read(); Path({str(pid_file)!r}).write_text(str(os.getpid())); [print('{{}}',flush=True) for _ in range(1000)]; time.sleep(30)"]
    abort = threading.Event()
    pages = manager._stream(command, "{}", tmp_path, [], abort, 5, None)
    assert next(pages) == {}
    time.sleep(0.1)
    abort.set()
    started = time.monotonic()
    with pytest.raises(PluginAborted):
        next(pages)
    assert time.monotonic() - started < 5
    if os.name != "nt":
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


@pytest.mark.parametrize("stream", [False, True])
def test_invalid_utf8_is_reported_without_hanging(tmp_path, stream):
    manager = PluginManager(SimpleNamespace(data_dir=tmp_path))
    command = [sys.executable, "-c", "import sys; sys.stdin.read(); sys.stdout.buffer.write(b'\\xff\\n')"]
    with pytest.raises(ValueError, match="UTF-8"):
        if stream:
            list(manager._stream(command, "{}", tmp_path, [], None, 5, None))
        else:
            manager._run_once(command, "{}", tmp_path, [], None, 5)
