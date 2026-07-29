from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session


def get_workspace_object(db: Session, model: Any, object_id: int, workspace_id: int, label: str) -> Any:
    item = db.get(model, object_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item
