from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime
class UserRead(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool

    model_config = {"from_attributes": True}


class WorkspaceRead(BaseModel):
    id: int
    name: str
    kind: str
    role: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    can_leave: bool = False


class AuthSession(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    workspace: WorkspaceRead
    workspaces: list[WorkspaceRead]


class BootstrapStatus(BaseModel):
    required: bool


class BootstrapCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    workspace_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    is_admin: bool = False
    can_add_gallery: bool = False
    can_delete_gallery: bool = False
    can_edit_gallery: bool = False
    can_add_samples: bool = False
    can_delete_samples: bool = False
    can_edit_samples: bool = False
    can_add_videos: bool = False
    can_delete_videos: bool = False
    can_edit_videos: bool = False


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class WorkspacePermissionUpdate(BaseModel):
    can_add_gallery: bool = False
    can_delete_gallery: bool = False
    can_edit_gallery: bool = False
    can_add_samples: bool = False
    can_delete_samples: bool = False
    can_edit_samples: bool = False
    can_add_videos: bool = False
    can_delete_videos: bool = False
    can_edit_videos: bool = False


class WorkspaceMemberRead(BaseModel):
    id: int
    user: UserRead
    role: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime


class WorkspaceInvitationCreate(WorkspacePermissionUpdate):
    username: str = Field(min_length=1, max_length=128)


class WorkspaceInvitationRead(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    inviter_username: str
    invitee_username: str
    status: str
    role: str
    permissions: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime
