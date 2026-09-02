from __future__ import annotations

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
