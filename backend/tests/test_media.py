from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from fastapi import HTTPException, Request

from app.http.media import (
    content_disposition,
    iter_storage_response,
    parse_range_header,
    stream_storage_object,
)


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
