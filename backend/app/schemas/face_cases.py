from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime


CaseIssueType = Literal["unknown", "wrong_person", "other"]
CaseAnswerType = Literal["known_person", "out_of_library", "not_person"]


class FaceCaseCreate(BaseModel):
    photo_id: int = Field(gt=0)
    face_id: int = Field(gt=0)
    face_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    answer_type: CaseAnswerType = "known_person"
    correct_person_id: int | None = Field(default=None, gt=0)
    excluded_person_id: int | None = Field(default=None, gt=0)
    issue_type: CaseIssueType
    notes: str = Field(default="", max_length=4000)
    bind_person: bool = False

    @model_validator(mode="after")
    def validate_answer(self):
        if self.answer_type == "known_person":
            if self.correct_person_id is None or self.excluded_person_id is not None:
                raise ValueError("库中人物标注必须指定正确人物，不能同时指定排除人物")
        else:
            if self.correct_person_id is not None or self.bind_person:
                raise ValueError("库外人物或排除人物标注不能指定正确人物或执行改绑")
            if self.answer_type == "not_person" and self.excluded_person_id is None:
                raise ValueError("请指定明确不是哪个人物")
            if self.answer_type == "out_of_library" and self.excluded_person_id is not None:
                raise ValueError("库外人物标注无需指定排除人物")
            if self.issue_type == "unknown":
                raise ValueError("库外人物或排除人物标注不能选择被判为未知")
        return self


class FaceCaseNotesUpdate(BaseModel):
    notes: str = Field(max_length=4000)


class FaceCaseRead(BaseModel):
    id: str
    source_photo_id: int | None
    source_face_id: int
    correct_person_id: int | None
    correct_person_name: str
    answer_type: CaseAnswerType
    excluded_person_id: int | None
    excluded_person_name: str | None
    issue_type: CaseIssueType
    notes: str
    embedding_version: str | None
    actor_name: str
    status: str
    cleanup_error: str | None
    created_at: datetime
    updated_at: datetime
    original_url: str
    thumbnail_url: str


class FaceCaseDetail(FaceCaseRead):
    snapshot: dict[str, Any]


class PaginatedFaceCases(BaseModel):
    items: list[FaceCaseRead]
    total: int
    offset: int
    limit: int


class FaceCaseExport(BaseModel):
    case_ids: list[str] | None = Field(default=None, max_length=5000)
    correct_person_name: str | None = Field(default=None, max_length=256)
    issue_type: CaseIssueType | None = None
    embedding_version: str | None = Field(default=None, max_length=64)
    answer_type: CaseAnswerType | None = None
