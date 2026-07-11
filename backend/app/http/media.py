from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse


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
        return StreamingResponse(iter_storage_response(response), media_type=media_type, headers=headers)

    start, end = range_tuple
    length = end - start + 1
    response = storage.get_stream(object_key, offset=start, length=length)
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        }
    )
    return StreamingResponse(
        iter_storage_response(response),
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
