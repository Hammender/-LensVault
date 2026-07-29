from datetime import datetime
from typing import Annotated

from pydantic import BaseModel as PydanticBaseModel, PlainSerializer, WithJsonSchema

from app.core.timezones import shanghai_isoformat


ShanghaiDateTime = Annotated[
    datetime,
    PlainSerializer(shanghai_isoformat, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


class BaseModel(PydanticBaseModel):
    pass
