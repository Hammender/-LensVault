from __future__ import annotations

import logging
from collections.abc import Iterator
from threading import Lock
from typing import Protocol
from urllib.parse import quote

import anyio
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

# 断开和删除打断不能进默认 40 线程池，否则会和堵在 stream() 里的读取互相等待。
_STREAM_CLOSE_LIMITER = anyio.CapacityLimiter(16)
_streams_lock = Lock()
_streams_by_key: dict[str, set["_StorageStreamingResponse"]] = {}


class StorageResponse(Protocol):
    def stream(self, chunk_size: int) -> Iterator[bytes]: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class ObjectStat(Protocol):
    size: int


class ObjectStorage(Protocol):
    def stat_object(self, object_key: str) -> ObjectStat: ...

    def get_stream(
        self,
        object_key: str,
        offset: int = 0,
        length: int | None = None,
    ) -> StorageResponse: ...


def parse_range_header(range_header: str | None, size: int) -> tuple[int, int] | None:
    if not range_header:
        return None
    unit, _, range_value = range_header.partition("=")
    if unit.strip().lower() != "bytes" or "," in range_value:
        raise _invalid_range(size)
    start_text, _, end_text = range_value.partition("-")
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(size - suffix_length, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError as exc:
        raise _invalid_range(size) from exc
    if start < 0 or end < start or start >= size:
        raise _invalid_range(size)
    return start, min(end, size - 1)


def iter_storage_response(response: StorageResponse, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    try:
        yield from response.stream(chunk_size)
    finally:
        response.close()
        response.release_conn()


class _StorageStreamingResponse(StreamingResponse):
    """客户端断开或发送失败时主动关闭上游，不依赖生成器被垃圾回收。"""

    def __init__(self, source: StorageResponse, *, object_key: str, **kwargs) -> None:
        self._source = source
        self._object_key = object_key
        self._interrupted = False
        self._released = False
        self._close_lock = Lock()
        self._iterator = self._chunks()
        self._register_stream()
        super().__init__(self._iterator, **kwargs)

    def _register_stream(self) -> None:
        with _streams_lock:
            _streams_by_key.setdefault(self._object_key, set()).add(self)

    def _unregister_stream(self) -> None:
        with _streams_lock:
            streams = _streams_by_key.get(self._object_key)
            if not streams:
                return
            streams.discard(self)
            if not streams:
                del _streams_by_key[self._object_key]

    def _interrupt_source(self) -> None:
        """只关闭上游响应，让堵在 stream() 里的读取返回。可从非读取线程调用。"""
        with self._close_lock:
            if self._interrupted:
                return
            self._interrupted = True
            try:
                self._source.close()
            except Exception:
                logger.exception("关闭媒体上游失败")

    def _release_source(self) -> None:
        """归还连接。读取线程的 finally 会调用；读取从未开始时由响应结束路径补一次。"""
        with self._close_lock:
            if self._released:
                return
            self._released = True
        try:
            self._source.release_conn()
        except Exception:
            logger.exception("归还媒体上游连接失败")
        self._unregister_stream()

    def _close_source(self) -> None:
        self._interrupt_source()
        self._release_source()

    def _release_if_reader_idle(self) -> None:
        """super() 已返回，读取线程不在生成器里。补上未启动或停在 yield 的归还。"""
        if self._released:
            return
        iterator = self._iterator
        if iterator.gi_running:
            return
        if iterator.gi_suspended:
            iterator.close()
            return
        self._release_source()

    def _chunks(self) -> Iterator[bytes]:
        try:
            yield from self._source.stream(1024 * 1024)
        finally:
            self._close_source()

    async def _interrupt_source_async(self) -> None:
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(self._interrupt_source, limiter=_STREAM_CLOSE_LIMITER)

    async def listen_for_disconnect(self, receive: Receive) -> None:
        try:
            await super().listen_for_disconnect(receive)
        finally:
            await self._interrupt_source_async()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # 外层 shield 盖住打断和补归还之间的取消点。这里不申请默认线程池。
            with anyio.CancelScope(shield=True):
                await self._interrupt_source_async()
                await anyio.to_thread.run_sync(self._release_if_reader_idle, limiter=_STREAM_CLOSE_LIMITER)


def interrupt_storage_streams(object_key: str) -> None:
    """打断本进程内正在读取该对象的媒体流。不归还连接，也不进入默认线程池。"""
    with _streams_lock:
        streams = list(_streams_by_key.get(object_key, ()))
    for stream in streams:
        stream._interrupt_source()


def content_disposition(
    disposition: str,
    filename: str,
    *,
    include_ascii_filename: bool = True,
) -> str:
    original = filename or "file"
    encoded = quote(original, safe="")
    if not include_ascii_filename:
        return f"{disposition}; filename*=UTF-8''{encoded}"
    fallback = "".join(ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\", ";"} else "_" for ch in original)
    fallback = fallback.strip(" ._") or "file"
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def stream_storage_object(
    storage: ObjectStorage,
    request: Request,
    object_key: str,
    filename: str,
    content_type: str | None,
    *,
    default_media_type: str = "application/octet-stream",
    include_ascii_filename: bool = True,
) -> StreamingResponse:
    stat = storage.stat_object(object_key)
    size = stat.size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": content_disposition(
            "inline",
            filename,
            include_ascii_filename=include_ascii_filename,
        ),
    }
    media_type = content_type or default_media_type
    range_tuple = parse_range_header(request.headers.get("range"), size)
    if range_tuple is None:
        response = storage.get_stream(object_key)
        headers["Content-Length"] = str(size)
        return _StorageStreamingResponse(
            response,
            object_key=object_key,
            media_type=media_type,
            headers=headers,
        )

    start, end = range_tuple
    length = end - start + 1
    response = storage.get_stream(object_key, offset=start, length=length)
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        }
    )
    return _StorageStreamingResponse(
        response,
        object_key=object_key,
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


def _invalid_range(size: int) -> HTTPException:
    return HTTPException(
        status_code=416,
        detail="Invalid range",
        headers={"Content-Range": f"bytes */{size}"},
    )
