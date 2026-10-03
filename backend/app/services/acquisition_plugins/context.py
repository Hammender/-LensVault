"""采集调用创建的临时目录由执行上下文统一拥有。"""

import shutil
import tempfile
import threading
from pathlib import Path


class PluginExecutionContext:
    def __init__(self, root: Path, abort_event=None, deadline=None):
        self.root = root
        self.abort_event = abort_event
        self.deadline = deadline
        self.credentials: dict[str, object] = {}
        self.manifest = None
        self._directory: Path | None = None
        self._lock = threading.Lock()

    @property
    def secrets(self) -> list[str]:
        return [value for value in self.credentials.values() if isinstance(value, str) and value]

    def download_directory(self) -> Path:
        with self._lock:
            if self._directory is None:
                self.root.mkdir(parents=True, exist_ok=True)
                self._directory = Path(tempfile.mkdtemp(prefix="run-", dir=self.root))
            return Path(tempfile.mkdtemp(prefix="download-", dir=self._directory))

    def close(self) -> None:
        with self._lock:
            if self._directory is not None:
                shutil.rmtree(self._directory, ignore_errors=True)
                self._directory = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
