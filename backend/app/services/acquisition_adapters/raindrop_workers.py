from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import parse_qsl, quote, urlparse, urlencode, urlunparse

from .contracts import RemoteItem, RemotePage, SourceAdapter, max_pages_from, stable_key


def _request_bytes(*args: object, **kwargs: object):
    from . import _request_bytes as request
    return request(*args, **kwargs)


class RaindropWorkersAdapter(SourceAdapter):
    def _normalize(self, raw_url: str) -> tuple[str, str]:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != "raindrop.ftxsri.workers.dev":
            raise ValueError("该脚本只支持 raindrop.ftxsri.workers.dev 的分类网页")
        if not [part for part in parsed.path.split("/") if part]:
            raise ValueError("分类 URL 中缺少集合标识")
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in {"ajax", "page", "sort"}]
        page_url = urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", urlencode(query), ""))
        return f"{parsed.scheme}://{parsed.netloc.lower()}", page_url

    def enumerate_pages(self, crawl_url: str, parameters: dict[str, object], known_external_keys: set[str], incremental: bool) -> Iterable[RemotePage]:
        base_url, page_url = self._normalize(crawl_url)
        max_pages = max_pages_from(parameters)
        page = 0
        seen: set[str] = set()
        while page <= 1000 and (max_pages is None or page < max_pages):
            parsed = urlparse(page_url)
            query = parse_qsl(parsed.query, keep_blank_values=True) + [("ajax", "1"), ("page", str(page)), ("sort", "-created")]
            request_url = urlunparse(parsed._replace(query=urlencode(query)))
            raw, _ = _request_bytes(request_url, "application/json,*/*;q=0.8", page_url)
            payload = json.loads(raw.decode("utf-8"))
            batch = (payload.get("items") or []) if isinstance(payload, dict) else []
            if not isinstance(batch, list):
                raise ValueError("Workers 采集接口未返回图片列表")
            if not batch:
                yield RemotePage(page_number=page + 1, items=(), stop_reason="collection_end")
                break
            page_keys: list[str] = []
            page_items: list[RemoteItem] = []
            for record in batch:
                if not isinstance(record, dict) or record.get("type") != "image":
                    continue
                link = str(record.get("link") or "").strip()
                cover = str(record.get("cover") or "").strip()
                if not link and not cover:
                    continue
                item_id = str(record.get("_id") or stable_key(link or cover))
                if item_id in seen:
                    continue
                seen.add(item_id)
                page_keys.append(item_id)
                candidates: list[str] = []
                for candidate in (
                    link,
                    f"{base_url}/get_cache_url?id={quote(item_id)}",
                    f"{base_url}/proxy?url={quote(link, safe='')}" if link else "",
                    cover,
                    f"{base_url}/proxy?url={quote(cover, safe='')}" if cover else "",
                ):
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
                page_items.append(RemoteItem(item_id, link or cover, cover or None, str(record.get("title") or "") or None, tuple(candidates)))
            natural_end = len(batch) < 30
            requested_end = max_pages is not None and page + 1 >= max_pages
            known_end = incremental and page_keys and all(key in known_external_keys for key in page_keys)
            stop_reason = "collection_end" if natural_end else "known_page" if known_end else "requested_end" if requested_end else None
            yield RemotePage(page_number=page + 1, items=tuple(page_items), stop_reason=stop_reason)
            if stop_reason is not None:
                break
            page += 1

