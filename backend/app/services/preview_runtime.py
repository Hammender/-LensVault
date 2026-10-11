"""图片预览的独立并发额度与同键请求合并。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from threading import RLock
from typing import TypeVar

import anyio


logger = logging.getLogger(__name__)
T = TypeVar("T")
_source_locks = tuple(RLock() for _ in range(64))


@contextmanager
def preview_source_guard(source_key: str):
    """同一进程内串行化某个原图的预览写入与清理。"""
    with _source_locks[hash(source_key) % len(_source_locks)]:
        yield


def preview_source_exists(storage, source_key: str) -> bool:
    try:
        stat = getattr(storage, "stat_object", None)
        if stat is not None:
            stat(source_key)
        else:
            storage.get_bytes(source_key)
    except Exception as exc:
        if getattr(exc, "code", None) in {"NoSuchKey", "NoSuchObject"} or isinstance(exc, (KeyError, FileNotFoundError)):
            return False
        raise
    return True


def put_preview_if_source_exists(storage, source_key: str, cache_key: str,
                                 payload: bytes, media_type: str) -> bool:
    with preview_source_guard(source_key):
        if not preview_source_exists(storage, source_key):
            return False
        storage.put_bytes(cache_key, payload, media_type)
        # 其他进程可能在 stat 与写入之间清理原图；写完再核对并回收孤儿缓存。
        if not preview_source_exists(storage, source_key):
            storage.remove_object(cache_key)
            return False
        return True


class PreviewRuntime:
    def __init__(self, parallel: int):
        self.limiter = anyio.CapacityLimiter(max(1, parallel))
        self.inflight: dict[str, asyncio.Task] = {}

    async def run(self, key: str, operation: Callable[[], T]) -> T:
        task = self.inflight.get(key)
        if task is None:
            queued_at = time.perf_counter()

            async def execute() -> T:
                def work() -> T:
                    waited_ms = (time.perf_counter() - queued_at) * 1000
                    started_at = time.perf_counter()
                    try:
                        return operation()
                    finally:
                        duration_ms = (time.perf_counter() - started_at) * 1000
                        if waited_ms >= 1000 or duration_ms >= 1000:
                            logger.warning("图片预览耗时 key=%s 排队=%.0fms 处理=%.0fms", key, waited_ms, duration_ms)

                return await anyio.to_thread.run_sync(work, limiter=self.limiter)

            task = asyncio.create_task(execute())
            self.inflight[key] = task

            def clear(finished: asyncio.Task) -> None:
                if self.inflight.get(key) is finished:
                    self.inflight.pop(key, None)
                if not finished.cancelled():
                    finished.exception()

            task.add_done_callback(clear)
        return await asyncio.shield(task)


def preview_runtime(request) -> PreviewRuntime:
    state = request.app.state
    runtime = getattr(state, "preview_runtime", None)
    if runtime is None:
        parallel = getattr(getattr(state, "settings", None), "image_compute_thumbnail_parallel", 2)
        runtime = PreviewRuntime(int(parallel))
        state.preview_runtime = runtime
    return runtime
