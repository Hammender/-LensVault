"""无需登录的 JSON 分页接口采集插件示例。实际网站的字段需由该网站插件自行适配。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


def _open(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("目标地址必须为完整的 HTTP(S) URL")
    request = Request(url, headers={"User-Agent": "PictureShow-Plugin/1"})
    return urlopen(request, timeout=30)


def test_connection(credentials: dict[str, object]) -> dict[str, object]:
    return {"ok": True}


def enumerate_pages(crawl_url: str, parameters: dict[str, object], credentials: dict[str, object],
                    known_external_keys: set[str], incremental: bool):
    parsed = urlparse(crawl_url)
    existing_query = [(key, value) for key, value in parse_qsl(parsed.query) if key != "page"]
    for number in range(1, int(parameters.get("max_pages") or 10) + 1):
        url = urlunparse(parsed._replace(query=urlencode([*existing_query, ("page", number)])))
        with _open(url) as response:
            payload = json.load(response)
        records = payload.get("items") or []
        items = []
        for record in records:
            external_key = str(record["id"])
            items.append({
                "external_key": external_key,
                "source_url": str(record["url"]),
                "title": str(record.get("title") or ""),
                "media_type": "video" if record.get("type") == "video" else "image",
                "public_metadata": {
                    "work_id": external_key,
                    **{key: record[key] for key in ("author", "column")
                       if isinstance(record.get(key), str)},
                    "original_title": str(record.get("title") or ""),
                },
            })
        end = not records or not payload.get("has_more")
        yield {"page_number": number, "items": items,
               "stop_reason": "collection_end" if end else None}
        if end:
            return


def download(item: dict[str, object], credentials: dict[str, object], temporary_dir: str) -> dict[str, str]:
    source = str(item["source_url"])
    filename = Path(urlparse(source).path).name or "media.bin"
    target = Path(temporary_dir) / filename
    with _open(source) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    return {"path": str(target)}
