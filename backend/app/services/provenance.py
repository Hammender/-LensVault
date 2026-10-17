"""来源快照、迁移包校验与摘要；不会自行提交事务。"""
from __future__ import annotations

from datetime import datetime
import json
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timezones import shanghai_now
from app.models import (
    AcquisitionAsset, AcquisitionCategory, AcquisitionRun, AcquisitionRunItem,
    AcquisitionSourceItem, AcquisitionTelegramHashtag, AcquisitionTelegramMessage,
    GalleryPhoto, MediaProvenance, TelegramProvenance, User,
)

SOURCE_TYPES = {"manual_upload", "import", "acquisition", "video_capture", "unknown"}
SECRET = re.compile(r"token|secret|password|passwd|cookie|authorization|credential|api[_-]?key|session|signature|access[_-]?hash", re.I)
TEXT_FIELDS = {
    "site_name": 128, "category_path": 1024, "run_id": 64, "plugin_key": 128,
    "plugin_version": 64, "original_url": 2048, "published_at": 64,
    "collected_at": 64, "imported_at": 64, "actor_name": 128,
    "record_method": 32, "original_sha256": 64,
}
TG_FIELDS = {
    "channel_id", "channel_title", "channel_username", "peer_id", "entity_type",
    "message_id", "topic_id", "topic_title", "is_comment", "root_channel_message_id",
    "root_channel_id", "root_channel_username", "reply_to_message_id", "grouped_id",
    "media_type", "transport_type", "original_filename", "message_url", "hashtags",
    "caption_excerpt", "caption_truncated",
}
CAPTURE_FIELDS = {"video_asset_id", "video_filename", "video_sha256", "frame_index", "time_seconds", "color_conversion"}


def public_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https", "tg"}:
            return None
        host = parts.netloc.rsplit("@", 1)[-1]
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not SECRET.search(k)])
        return urlunsplit((parts.scheme, host, parts.path, query, ""))[:2048]
    except ValueError:
        return None


def _public(value, depth=0):
    if depth > 4:
        return None
    if isinstance(value, dict):
        return {str(k)[:128]: _public(v, depth + 1) for k, v in list(value.items())[:100] if not SECRET.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [_public(v, depth + 1) for v in value[:100]]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        if re.search(r"(?:Bearer\s+|(?:password|token|secret|cookie)\s*[:=])", value, re.I):
            return "[已脱敏]"
        return public_url(value) if value.startswith(("http://", "https://", "tg://")) else value[:2048]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def public_metadata(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("公开来源元数据必须是对象")
    cleaned = _public(value)
    if len(json.dumps(cleaned, ensure_ascii=False).encode("utf-8")) > 16384:
        return {"metadata_truncated": True}
    return cleaned


def normalize_snapshot(value: dict | None, *, imported=False) -> dict:
    if value is None:
        return {"version": 1, "source_type": "unknown"}
    if not isinstance(value, dict) or value.get("version", 1) != 1:
        raise ValueError("来源快照格式或版本不支持")
    if len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) > 65536:
        raise ValueError("来源快照超过64 KiB")
    kind = value.get("source_type", "unknown")
    if kind not in SOURCE_TYPES:
        raise ValueError("来源类型无效")
    result = {"version": 1, "source_type": kind}
    for key, limit in TEXT_FIELDS.items():
        v = value.get(key)
        if v is not None:
            if isinstance(v, datetime):
                v = v.isoformat()
            if not isinstance(v, str):
                raise ValueError(f"来源字段格式无效：{key}")
            result[key] = public_url(v) if key == "original_url" else v[:limit]
    for key, allowed in (("telegram", TG_FIELDS), ("capture", CAPTURE_FIELDS)):
        v = value.get(key)
        if v is not None:
            if not isinstance(v, dict):
                raise ValueError(f"来源字段格式无效：{key}")
            result[key] = _public({k: v[k] for k in allowed if k in v})
    if "telegram" in result:
        tg = result["telegram"]
        caption = tg.get("caption_excerpt")
        if caption is not None:
            if not isinstance(caption, str):
                raise ValueError("来源文案摘要格式无效")
            tg["caption_excerpt"] = caption[:50]
            tg["caption_truncated"] = bool(tg.get("caption_truncated") or len(caption) > 50)
    result["public_metadata"] = public_metadata(value.get("public_metadata"))
    if value.get("upstream") is not None:
        upstream = value["upstream"]
        if not isinstance(upstream, dict) or "upstream" in upstream:
            raise ValueError("原始来源不得嵌套搬运历史")
        result["upstream"] = normalize_snapshot(upstream)
    if imported:
        result["record_method"] = "imported_package"
    return result


def actor_snapshot(db: Session, user_id: int | None, actor_name: str | None = None) -> str | None:
    if actor_name:
        return actor_name[:128]
    user = db.get(User, user_id) if user_id else None
    return (user.display_name or user.username) if user else None


def attach_provenance(db: Session, media, *, source_type="manual_upload", actor_id=None,
                      actor_name=None, snapshot=None, record_method="recorded") -> MediaProvenance:
    if media.provenance is not None:
        return media.provenance
    data = normalize_snapshot(snapshot or {"source_type": source_type})
    data["source_type"] = source_type
    if media.sha256:
        data.setdefault("original_sha256", media.sha256)
    name = actor_snapshot(db, actor_id, actor_name)
    data.update(actor_name=name, imported_at=media.created_at or shanghai_now(), record_method=record_method)
    data = normalize_snapshot(data)
    media.created_by = actor_id
    media.actor_name = name
    tg = data.pop("telegram", None)
    source = MediaProvenance(
        workspace_id=media.workspace_id, source_type=source_type, actor_name=name,
        site_name=data.get("site_name"), category_path=data.get("category_path"),
        record_method=record_method, imported_at=media.created_at or shanghai_now(),
        snapshot_json=json.dumps(data, ensure_ascii=False),
    )
    if isinstance(media, GalleryPhoto):
        source.photo_id = media.id
    else:
        source.video_id = media.id
    if tg:
        source.telegram = TelegramProvenance(snapshot_json=json.dumps(tg, ensure_ascii=False))
    media.provenance = source
    db.add(source)
    return source


def source_summary(media) -> dict:
    source = getattr(media, "provenance", None)
    if source is None:
        return {"source_type": "unknown", "text": "历史来源未知", "has_details": False}
    kind = source.source_type
    if kind == "acquisition":
        text = " · ".join(filter(None, [source.site_name, source.category_path])) or "采集"
    elif kind == "video_capture":
        text = " · ".join(filter(None, ["视频截图", source.site_name, source.category_path]))
    else:
        text = {"manual_upload": "手动上传", "import": "导入", "unknown": "历史来源未知"}.get(kind, "历史来源未知")
        if source.actor_name:
            text += " · " + source.actor_name
    return {"source_type": kind, "text": text, "has_details": True,
            "site_name": source.site_name, "category_path": source.category_path,
            "actor_name": source.actor_name, "record_method": source.record_method}


def export_source(media) -> dict | None:
    source = getattr(media, "provenance", None)
    if source is None:
        return None
    data = json.loads(source.snapshot_json)
    if source.telegram:
        data["telegram"] = json.loads(source.telegram.snapshot_json)
    return normalize_snapshot(data)


def imported_snapshot(value) -> dict:
    data = normalize_snapshot(value, imported=True)
    root = data.get("upstream") or data
    return {"version": 1, "source_type": "import", "upstream": root}


def acquisition_snapshot(db: Session, run: AcquisitionRun, category: AcquisitionCategory | None,
                         *, url=None, telegram=None, public_data=None, published_at=None) -> dict:
    data = {
        "source_type": "acquisition", "site_name": run.source_name_snapshot,
        "category_path": category.path if category else run.category_name_snapshot,
        "run_id": run.id, "plugin_key": run.script_key,
        "plugin_version": run.script_version_snapshot, "original_url": url,
        "collected_at": shanghai_now(), "published_at": published_at,
        "public_metadata": public_data,
    }
    if telegram:
        data["telegram"] = {k: telegram[k] for k in TG_FIELDS if k in telegram}
        data["telegram"]["hashtags"] = [tag[0] if isinstance(tag, (list, tuple)) and tag else tag for tag in (telegram.get("hashtags") or [])]
        caption = telegram.get("caption") or ""
        data["telegram"].update(caption_excerpt=caption[:50], caption_truncated=len(caption) > 50,
                                message_url=telegram.get("source_url") or telegram.get("message_url"))
    return normalize_snapshot(data)


def asset_source(db: Session, asset: AcquisitionAsset) -> dict:
    if asset.capture_metadata_json:
        capture = json.loads(asset.capture_metadata_json)
        base = capture.get("provenance") or {"source_type": "video_capture", "original_url": capture.get("source_message_url")}
        data = normalize_snapshot(base)
        data.update(source_type="video_capture", capture={k: capture[k] for k in CAPTURE_FIELDS if k in capture})
        return normalize_snapshot(data)
    item = db.scalar(select(AcquisitionRunItem).join(AcquisitionRun).where(
        AcquisitionRunItem.asset_id == asset.id, AcquisitionRun.workspace_id == asset.workspace_id,
    ).order_by(AcquisitionRunItem.created_at, AcquisitionRunItem.id).limit(1))
    if item is None:
        return {"source_type": "acquisition"}
    if item.source_snapshot_json:
        return normalize_snapshot(json.loads(item.source_snapshot_json))
    run = db.get(AcquisitionRun, item.run_id)
    source_item = db.get(AcquisitionSourceItem, item.source_item_id)
    category = db.get(AcquisitionCategory, run.category_id)
    tg = db.scalar(select(AcquisitionTelegramMessage).where(AcquisitionTelegramMessage.source_item_id == item.source_item_id))
    telegram = None
    if tg:
        telegram = {key: getattr(tg, key, None) for key in TG_FIELDS}
        telegram["caption"] = tg.caption
        telegram["hashtags"] = list(db.scalars(select(AcquisitionTelegramHashtag.tag_raw).where(AcquisitionTelegramHashtag.telegram_message_id == tg.id)))
    data = acquisition_snapshot(db, run, category, url=source_item.source_url if source_item else None,
                                telegram=telegram, published_at=tg.published_at if tg else None)
    data["collected_at"] = item.created_at.isoformat()
    return data
