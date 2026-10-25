from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import anyio
import pytest
from fastapi import HTTPException, Request

from app.http.media import (
    content_disposition,
    interrupt_storage_streams,
    iter_storage_response,
    parse_range_header,
    stream_storage_object,
)
from app.models import AcquisitionAsset


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 100, None),
        ("bytes=0-9", 100, (0, 9)),
        ("bytes=90-", 100, (90, 99)),
        ("bytes=-10", 100, (90, 99)),
        ("bytes=95-200", 100, (95, 99)),
    ],
)
def test_parse_range_header(header: str | None, size: int, expected: tuple[int, int] | None) -> None:
    assert parse_range_header(header, size) == expected


@pytest.mark.parametrize("header", ["items=0-1", "bytes=1-0", "bytes=100-", "bytes=0-1,3-4", "bytes=-0"])
def test_parse_range_header_rejects_invalid_values(header: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_range_header(header, 100)
    assert exc_info.value.status_code == 416
    assert exc_info.value.headers == {"Content-Range": "bytes */100"}


def test_content_disposition_keeps_ascii_fallback_and_utf8_name() -> None:
    value = content_disposition("inline", "示例;图.jpg")
    assert value == 'inline; filename="jpg"; filename*=UTF-8\'\'%E7%A4%BA%E4%BE%8B%3B%E5%9B%BE.jpg'
    assert content_disposition("inline", "视频.mp4", include_ascii_filename=False) == (
        "inline; filename*=UTF-8''%E8%A7%86%E9%A2%91.mp4"
    )


class FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False
        self.released = False

    def stream(self, chunk_size: int):
        assert chunk_size == 1024 * 1024
        yield from self.chunks

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


@dataclass
class FakeStat:
    size: int


class FakeStorage:
    def __init__(self, size: int = 10) -> None:
        self.size = size
        self.calls: list[tuple[str, int, int | None]] = []
        self.responses: list[FakeResponse] = []

    def stat_object(self, object_key: str) -> FakeStat:
        assert object_key == "media/object"
        return FakeStat(self.size)

    def get_stream(self, object_key: str, offset: int = 0, length: int | None = None) -> FakeResponse:
        self.calls.append((object_key, offset, length))
        response = FakeResponse([b"payload"])
        self.responses.append(response)
        return response


def make_request(range_header: str | None = None) -> Request:
    headers = [] if range_header is None else [(b"range", range_header.encode("ascii"))]
    return Request({"type": "http", "method": "GET", "path": "/media", "headers": headers})


def test_stream_storage_object_builds_full_response_headers() -> None:
    storage = FakeStorage()
    response = stream_storage_object(storage, make_request(), "media/object", "图片.jpg", "image/jpeg")
    assert response.status_code == 200
    assert response.media_type == "image/jpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "10"
    assert storage.calls == [("media/object", 0, None)]


def test_stream_storage_object_builds_partial_response_headers() -> None:
    storage = FakeStorage()
    response = stream_storage_object(storage, make_request("bytes=2-5"), "media/object", "video.mp4", "video/mp4")
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert storage.calls == [("media/object", 2, 4)]


def test_iter_storage_response_releases_connection() -> None:
    source = FakeResponse([b"a", b"b"])
    assert list(iter_storage_response(source)) == [b"a", b"b"]
    assert source.closed is True
    assert source.released is True


@pytest.mark.parametrize("range_header", [None, "bytes=2-5"])
def test_stream_disconnect_closes_upstream_while_body_is_paused(range_header) -> None:
    storage = FakeStorage()
    response = stream_storage_object(storage, make_request(range_header), "media/object", "video.mp4", "video/mp4")
    source = storage.responses[0]

    async def run():
        disconnected = asyncio.Event()

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                disconnected.set()
                # 模拟浏览器暂停读取，生成器仍停在 yield，尚未自然结束。
                await asyncio.Event().wait()

        await asyncio.wait_for(response(make_request(range_header).scope, receive, send), timeout=2)
        assert source.closed and source.released

    asyncio.run(run())


def test_stream_send_failure_before_first_chunk_closes_upstream() -> None:
    storage = FakeStorage()
    request = make_request()
    response = stream_storage_object(storage, request, "media/object", "video.mp4", "video/mp4")

    async def run():
        async def receive():
            await asyncio.Event().wait()

        async def send(_message):
            raise RuntimeError("客户端连接已断开")

        with pytest.raises(Exception):
            await response(request.scope, receive, send)
        assert storage.responses[0].closed and storage.responses[0].released

    asyncio.run(run())


def test_stream_server_cancellation_closes_upstream() -> None:
    storage = FakeStorage()
    request = make_request()
    response = stream_storage_object(storage, request, "media/object", "video.mp4", "video/mp4")

    async def run():
        body_started = asyncio.Event()

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body":
                body_started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(response(request.scope, receive, send))
        await asyncio.wait_for(body_started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert storage.responses[0].closed and storage.responses[0].released

    asyncio.run(run())


class _BlockingSource:
    """stream() 停在 close() 才会放开的事件上，用来区分「停在 yield」和「停在读取内部」。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.unblocked = threading.Event()
        self.closed = threading.Event()
        self.close_time: float | None = None
        self.return_time: float | None = None
        self.released = False

    def stream(self, chunk_size: int):
        assert chunk_size == 1024 * 1024
        self.started.set()
        if not self.unblocked.wait(timeout=5):
            raise AssertionError("close() 未放开阻塞的 stream()")
        self.return_time = time.perf_counter()
        yield b"payload"

    def close(self) -> None:
        self.close_time = time.perf_counter()
        self.closed.set()
        self.unblocked.set()

    def release_conn(self) -> None:
        self.released = True


class _KeyStorage:
    def __init__(self, source: object, object_key: str, size: int = 8) -> None:
        self.source = source
        self.object_key = object_key
        self.size = size

    def stat_object(self, object_key: str) -> FakeStat:
        assert object_key == self.object_key
        return FakeStat(self.size)

    def get_stream(self, object_key: str, offset: int = 0, length: int | None = None):
        assert object_key == self.object_key
        return self.source


def test_stream_blocked_inside_stream_is_closed_on_cancel() -> None:
    source = _BlockingSource()
    storage = _KeyStorage(source, "media/blocked-inside-stream")
    request = make_request()
    response = stream_storage_object(storage, request, storage.object_key, "video.mp4", "video/mp4")

    async def run() -> None:
        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body":
                await asyncio.Event().wait()

        task = asyncio.create_task(response(request.scope, receive, send))
        await asyncio.wait_for(asyncio.to_thread(source.started.wait, 2), timeout=2)
        assert source.started.is_set()
        task.cancel()
        done, _pending = await asyncio.wait({task}, timeout=2)
        assert done, "取消后任务未在 2 秒内结束"
        with pytest.raises(asyncio.CancelledError):
            task.result()
        assert source.close_time is not None and source.return_time is not None
        assert source.close_time < source.return_time
        assert source.released is True

    asyncio.run(run())


def test_stream_disconnect_closes_when_default_thread_limiter_is_full() -> None:
    source = _BlockingSource()
    storage = _KeyStorage(source, "media/limiter-full")
    request = make_request()
    response = stream_storage_object(storage, request, storage.object_key, "video.mp4", "video/mp4")

    async def run() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        total = int(limiter.total_tokens)
        assert total == 40
        blockers = [threading.Event() for _ in range(total)]
        disconnect_now = asyncio.Event()
        occupy_tasks: list[asyncio.Task[None]] = []
        response_task: asyncio.Task[None] | None = None

        async def receive():
            await disconnect_now.wait()
            return {"type": "http.disconnect"}

        async def send(_message):
            return None

        async def occupy(blocker: threading.Event) -> None:
            await anyio.to_thread.run_sync(blocker.wait)

        try:
            response_task = asyncio.create_task(response(request.scope, receive, send))
            await asyncio.wait_for(asyncio.to_thread(source.started.wait, 2), timeout=2)
            assert source.started.is_set()
            for blocker in blockers:
                occupy_tasks.append(asyncio.create_task(occupy(blocker)))
            deadline = time.perf_counter() + 2
            while limiter.borrowed_tokens < total:
                if time.perf_counter() > deadline:
                    raise AssertionError(f"默认线程池未被占满 borrowed={limiter.borrowed_tokens} total={total}")
                await asyncio.sleep(0.01)
            started = time.perf_counter()
            disconnect_now.set()
            while not source.closed.is_set():
                if time.perf_counter() - started > 1:
                    raise AssertionError("默认线程池占满时，断开后 1 秒内没有 close()")
                await asyncio.sleep(0.005)
            await asyncio.wait_for(response_task, timeout=2)
            assert source.released is True
        finally:
            for blocker in blockers:
                blocker.set()
            pending: list[asyncio.Task] = [task for task in occupy_tasks if not task.done()]
            if response_task is not None and not response_task.done():
                response_task.cancel()
                pending.append(response_task)
            if pending:
                await asyncio.wait(pending, timeout=5)

    asyncio.run(run())


def test_interrupt_storage_streams_closes_without_release_conn() -> None:
    interrupt_storage_streams("media/not-registered")

    source = FakeResponse([b"payload"])
    storage = _KeyStorage(source, "media/interrupt-me")
    request = make_request()
    response = stream_storage_object(storage, request, storage.object_key, "video.mp4", "video/mp4")

    interrupt_storage_streams(storage.object_key)
    assert source.closed is True
    assert source.released is False

    async def drain() -> None:
        async def receive():
            await asyncio.Event().wait()

        async def send(_message):
            return None

        await asyncio.wait_for(response(request.scope, receive, send), timeout=2)

    asyncio.run(drain())
    assert source.released is True
    assert source.closed is True


def test_reject_and_cleanup_interrupt_stream_before_remove(db_session) -> None:
    from app.services.acquisition import AcquisitionService

    class RecordingSource:
        def __init__(self) -> None:
            self.closed = False
            self.released = False

        def stream(self, chunk_size: int):
            yield b"payload"

        def close(self) -> None:
            self.closed = True

        def release_conn(self) -> None:
            self.released = True

    class RecordingStorage:
        def __init__(self) -> None:
            self.sources: dict[str, RecordingSource] = {}
            self.removed: list[tuple[str, bool, bool]] = []

        def stat_object(self, object_key: str) -> FakeStat:
            return FakeStat(4)

        def get_stream(self, object_key: str, offset: int = 0, length: int | None = None) -> RecordingSource:
            source = self.sources.setdefault(object_key, RecordingSource())
            return source

        def remove_object(self, object_key: str) -> None:
            source = self.sources.get(object_key)
            self.removed.append(
                (
                    object_key,
                    bool(source and source.closed),
                    bool(source and source.released),
                )
            )

    storage = RecordingStorage()
    reject_key = "acquisition/reject-original.mp4"
    cleanup_key = "acquisition/cleanup-original.mp4"
    reject_response = stream_storage_object(storage, make_request(), reject_key, "a.mp4", "video/mp4")
    cleanup_response = stream_storage_object(storage, make_request(), cleanup_key, "b.mp4", "video/mp4")
    created_at = datetime(2026, 8, 14, 10, 0, 0)
    reject_asset = AcquisitionAsset(
        id="reject-stream",
        sha256="a" * 64,
        filename="a.mp4",
        media_type="video",
        object_key=reject_key,
        size_bytes=4,
        status="pending_review",
        created_at=created_at,
        updated_at=created_at,
    )
    cleanup_asset = AcquisitionAsset(
        id="cleanup-stream",
        sha256="b" * 64,
        filename="b.mp4",
        media_type="video",
        object_key=cleanup_key,
        size_bytes=4,
        status="pending_review",
        created_at=created_at,
        updated_at=created_at,
    )
    untouched = AcquisitionAsset(
        id="no-object",
        sha256="c" * 64,
        filename="c.jpg",
        media_type="image",
        object_key=None,
        size_bytes=0,
        status="pending_review",
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add_all([reject_asset, cleanup_asset, untouched])
    db_session.commit()
    service = AcquisitionService(storage, object(), object(), similarity_extractor=object())
    try:
        assert service.reject_assets(db_session, None, [reject_asset.id, untouched.id]) == 2
        original_remove = next(item for item in storage.removed if item[0] == reject_key)
        assert original_remove == (reject_key, True, False)
        assert storage.sources[reject_key].released is False
        assert reject_asset.status == "rejected"
        assert reject_asset.object_key is None
        assert untouched.status == "rejected"
        assert untouched.object_key is None

        service._cleanup_asset_object(db_session, cleanup_asset)
        cleanup_remove = next(item for item in storage.removed if item[0] == cleanup_key)
        assert cleanup_remove == (cleanup_key, True, False)
        assert storage.sources[cleanup_key].released is False
        assert cleanup_asset.object_key is None
    finally:
        reject_response._release_source()
        cleanup_response._release_source()
