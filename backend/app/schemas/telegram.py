from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime


class TelegramAccountRead(BaseModel):
    workspace_id: int
    api_id: int | None = None
    phone_masked: str | None
    telegram_user_id: int | None
    username: str | None
    status: str
    code_delivery: str | None = None
    last_login_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class TelegramLoginStartRequest(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=16, max_length=256)
    phone_number: str = Field(min_length=4, max_length=64)


class TelegramLoginVerifyRequest(BaseModel):
    code: str = Field(min_length=3, max_length=32)
    password: str | None = Field(default=None, max_length=256)


class TelegramChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    channel_ref: str = Field(min_length=3, max_length=2048)
    notes: str | None = Field(default=None, max_length=2000)
    peer_id: str | None = Field(default=None, max_length=128)
    entity_type: Literal["channel", "group", "bot"] | None = None
    username: str | None = Field(default=None, max_length=256)
    topic_id: int | None = None
    topic_title: str | None = Field(default=None, max_length=256)
    source_mode: Literal["manual", "dialog"] = "manual"


class TelegramDialogRead(BaseModel):
    peer_id: str
    title: str
    username: str | None = None
    entity_type: str
    is_bot: bool = False
    is_forum: bool = False
    unread_count: int = 0


class TelegramTopicRead(BaseModel):
    topic_id: int
    title: str
    closed: bool = False
    pinned: bool = False
    date: datetime | None = None


class TelegramForumScanRead(BaseModel):
    is_forum: bool
    peer_id: str
    title: str
    username: str | None = None
    entity_type: str
    topics: list[TelegramTopicRead] = []
