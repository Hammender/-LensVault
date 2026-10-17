"""将已确认的历史未知视频来源改为指定用户的手动上传，核对预期数量并一次事务提交。"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import MediaProvenance, User, VideoItem


def reclassify(db: Session, *, user_id: int, expected_count: int) -> int:
    user = db.get(User, user_id)
    if user is None:
        raise ValueError("指定的上传用户不存在")
    rows = db.execute(select(VideoItem, MediaProvenance).join(
        MediaProvenance, MediaProvenance.video_id == VideoItem.id,
    ).where(MediaProvenance.source_type == "unknown").order_by(VideoItem.id)).all()
    if len(rows) != expected_count:
        raise ValueError(f"未知来源视频数量已变化：预计 {expected_count}，当前 {len(rows)}")
    name = user.display_name or user.username
    for video, source in rows:
        if source.record_method != "backfilled" or source.workspace_id != video.workspace_id:
            raise ValueError(f"视频 {video.id} 的来源记录不属于历史回填，已停止")
        details = json.loads(source.snapshot_json)
        if details.get("source_type") != "unknown":
            raise ValueError(f"视频 {video.id} 的来源快照与类型不一致，已停止")
        details.update(source_type="manual_upload", actor_name=name)
        video.created_by = user.id
        video.actor_name = name
        source.source_type = "manual_upload"
        source.actor_name = name
        source.snapshot_json = json.dumps(details, ensure_ascii=False)
    db.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    args = parser.parse_args()
    engine = create_engine(get_settings().database_url)
    try:
        with Session(engine) as db:
            print(json.dumps({"已修正视频": reclassify(db, user_id=args.user_id, expected_count=args.expected_count)}, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
