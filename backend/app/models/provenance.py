from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.core.timezones import shanghai_now


class MediaProvenance(Base):
    __tablename__ = "media_provenance"
    __table_args__ = (
        CheckConstraint("(photo_id IS NOT NULL AND video_id IS NULL) OR (photo_id IS NULL AND video_id IS NOT NULL)", name="ck_provenance_one_media"),
        {"comment": "正式素材的首次入库来源快照"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="来源编号")
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, comment="所属工作区")
    photo_id: Mapped[int | None] = mapped_column(ForeignKey("gallery_photos.id", ondelete="CASCADE"), unique=True, comment="所属图片，与视频互斥")
    video_id: Mapped[int | None] = mapped_column(ForeignKey("video_items.id", ondelete="CASCADE"), unique=True, comment="所属视频，与图片互斥")
    source_type: Mapped[str] = mapped_column(String(32), comment="上传、导入、采集、截图或历史未知")
    actor_name: Mapped[str | None] = mapped_column(String(128), comment="入库人名称快照")
    site_name: Mapped[str | None] = mapped_column(String(128), comment="站点名称快照")
    category_path: Mapped[str | None] = mapped_column(String(1024), comment="分类路径快照")
    record_method: Mapped[str] = mapped_column(String(32), default="recorded", comment="实时记录或历史回填")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, comment="本次正式入库时间")
    snapshot_json: Mapped[str] = mapped_column(Text, deferred=True, comment="已校验脱敏的来源详情及原始上游快照")
    telegram: Mapped[TelegramProvenance | None] = relationship(cascade="all, delete-orphan", uselist=False, lazy="select")


class TelegramProvenance(Base):
    __tablename__ = "telegram_provenance"
    __table_args__ = {"comment": "来源的Telegram平台信息快照"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="平台快照编号")
    provenance_id: Mapped[int] = mapped_column(ForeignKey("media_provenance.id", ondelete="CASCADE"), unique=True, comment="所属正式来源")
    snapshot_json: Mapped[str] = mapped_column(Text, comment="会话、话题、消息、发送形式、标签及文案摘要")


class VideoExportJob(Base):
    __tablename__ = "video_export_jobs"
    __table_args__ = {"comment": "视频素材包后台导出任务"}

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="导出任务编号")
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, comment="所属工作区")
    status: Mapped[str] = mapped_column(String(32), default="queued", comment="排队、执行、完成、失败或过期")
    selection_json: Mapped[str] = mapped_column(Text, comment="请求时冻结的视频编号")
    result_json: Mapped[str | None] = mapped_column(Text, comment="成功数量及逐项错误报告")
    object_key: Mapped[str | None] = mapped_column(String(512), comment="导出包对象存储键")
    filename: Mapped[str | None] = mapped_column(String(128), comment="下载文件名")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, comment="创建时间")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, comment="导出文件过期时间")
