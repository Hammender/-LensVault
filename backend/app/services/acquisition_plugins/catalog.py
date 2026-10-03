"""插件目录快照、管理操作串行化和版本使用引用。"""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from types import MappingProxyType


class PluginCatalog:
    def __init__(self):
        self.lock = RLock()
        self._active = {}
        self.known_keys = frozenset()
        self._users: dict[tuple[str, str], int] = {}
        self.preparing_ids: set[int] = set()

    @property
    def active(self):
        return MappingProxyType(deepcopy(self._active))

    def replace(self, active, known_keys):
        with self.lock:
            self._active = deepcopy(active)
            self.known_keys = frozenset(known_keys)

    @contextmanager
    def lease(self, manifest):
        identity = (str(manifest["key"]), str(manifest["version"]))
        with self.lock:
            self._users[identity] = self._users.get(identity, 0) + 1
        try:
            yield deepcopy(manifest)
        finally:
            with self.lock:
                count = self._users[identity] - 1
                if count:
                    self._users[identity] = count
                else:
                    del self._users[identity]

    def in_use(self, key, version):
        with self.lock:
            return bool(self._users.get((key, version)))
