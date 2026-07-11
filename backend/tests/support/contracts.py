from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute


IGNORED_OPENAPI_FIELDS = {"operationId"}


def normalize_openapi(document: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(document)

    def remove_ignored_fields(value: object) -> None:
        if isinstance(value, dict):
            for field in IGNORED_OPENAPI_FIELDS:
                value.pop(field, None)
            for child in value.values():
                remove_ignored_fields(child)
        elif isinstance(value, list):
            for child in value:
                remove_ignored_fields(child)

    remove_ignored_fields(normalized)
    return normalized


def ordered_route_table(app: FastAPI) -> list[dict[str, object]]:
    return [
        {
            "path": route.path,
            "methods": sorted(route.methods or ()),
        }
        for route in app.routes
        if isinstance(route, APIRoute)
    ]
