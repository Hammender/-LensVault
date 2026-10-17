from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.models import Person, User, Workspace, WorkspaceMember
from app.services.auth import create_access_token
from tests.support.app_loader import load_test_main


PERMISSION_CASES = (
    ("can_add_gallery", "POST", "/api/gallery/photos/import", "/api/gallery/photos/import"),
    ("can_delete_gallery", "DELETE", "/api/gallery/photos/1", "/api/gallery/photos/{photo_id}"),
    ("can_edit_gallery", "PATCH", "/api/gallery/photos/1/rich-text", "/api/gallery/photos/{photo_id}/rich-text"),
    ("can_edit_gallery", "PATCH", "/api/gallery/similarity-scans/scan-1/groups/1", "/api/gallery/similarity-scans/{scan_id}/groups/{group_id}"),
    ("can_delete_gallery", "POST", "/api/gallery/similarity-scans/scan-1/auto-delete-exact-mirrors", "/api/gallery/similarity-scans/{scan_id}/auto-delete-exact-mirrors"),
    ("can_add_samples", "POST", "/api/persons/1/samples", "/api/persons/{person_id}/samples"),
    ("can_add_samples", "POST", "/api/gallery/photos/1/faces/2/sample", "/api/gallery/photos/{photo_id}/faces/{face_id}/sample"),
    ("can_edit_gallery", "PATCH", "/api/gallery/photos/1/faces/2/person", "/api/gallery/photos/{photo_id}/faces/{face_id}/person"),
    ("can_edit_gallery", "DELETE", "/api/gallery/photos/1/faces/2/person", "/api/gallery/photos/{photo_id}/faces/{face_id}/person"),
    ("can_delete_samples", "DELETE", "/api/persons/1/samples/1", "/api/persons/{person_id}/samples/{sample_photo_id}"),
    ("can_edit_samples", "PATCH", "/api/persons/1", "/api/persons/{person_id}"),
    ("can_add_videos", "POST", "/api/videos/import-zip", "/api/videos/import-zip"),
    ("can_add_videos", "POST", "/api/videos/upload-sessions", "/api/videos/upload-sessions"),
    ("can_delete_videos", "DELETE", "/api/videos/1", "/api/videos/{video_id}"),
    ("can_edit_videos", "PATCH", "/api/videos/1", "/api/videos/{video_id}"),
)


def make_request(method: str, path: str, route_path: str | None = None) -> Request:
    scope = {"type": "http", "method": method, "path": path, "headers": []}
    if route_path is not None:
        scope["route"] = SimpleNamespace(path=route_path)
    return Request(scope)


def make_member_context(module):
    permissions = {field: False for field in module.PERMISSION_FIELDS}
    membership = SimpleNamespace(role="member", **permissions)
    return module.CurrentContext(
        user=SimpleNamespace(),
        workspace_id=1,
        role="member",
        workspace=SimpleNamespace(),
        membership=membership,
    )


@pytest.mark.parametrize(("permission", "method", "path", "route_path"), PERMISSION_CASES)
def test_permission_matrix_keeps_existing_route_rules(
    permission: str,
    method: str,
    path: str,
    route_path: str,
) -> None:
    module = load_test_main()
    current = make_member_context(module)

    with pytest.raises(HTTPException) as exc_info:
        module._enforce_request_permission(make_request(method, path, route_path), current)
    assert exc_info.value.status_code == 403

    setattr(current.membership, permission, True)
    module._enforce_request_permission(make_request(method, path, route_path), current)


def test_read_requests_do_not_require_modify_permission() -> None:
    module = load_test_main()
    module._enforce_request_permission(make_request("GET", "/api/gallery/photos"), make_member_context(module))


def test_workspace_object_lookup_rejects_cross_workspace_access(db_session: Session) -> None:
    module = load_test_main()
    first = Workspace(name="空间一", kind="shared")
    second = Workspace(name="空间二", kind="shared")
    db_session.add_all([first, second])
    db_session.flush()
    person = Person(workspace_id=first.id, name="测试人物", display_name="测试人物")
    db_session.add(person)
    db_session.commit()

    assert module._get_workspace_object(db_session, Person, person.id, first.id, "person") is person
    with pytest.raises(HTTPException) as exc_info:
        module._get_workspace_object(db_session, Person, person.id, second.id, "person")
    assert exc_info.value.status_code == 404


def test_require_context_selects_authorized_workspace(db_session: Session) -> None:
    module = load_test_main()
    user = User(username="tester", display_name="测试用户", password_hash="unused")
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(name="测试空间", kind="private", owner_user_id=user.id)
    db_session.add(workspace)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db_session.commit()

    token = create_access_token(user.id, module.settings.auth_secret_key, 5)
    current = module.require_context(
        make_request("GET", "/api/persons"),
        authorization=f"Bearer {token}",
        session_token=None,
        workspace_id_query=None,
        x_workspace_id=workspace.id,
        db=db_session,
    )

    assert current.user.id == user.id
    assert current.workspace_id == workspace.id
    assert current.role == "owner"


def test_require_context_rejects_workspace_without_membership(db_session: Session) -> None:
    module = load_test_main()
    user = User(username="limited", display_name="受限用户", password_hash="unused")
    db_session.add(user)
    db_session.flush()
    owned = Workspace(name="有权限空间", kind="private", owner_user_id=user.id)
    forbidden = Workspace(name="无权限空间", kind="shared")
    db_session.add_all([owned, forbidden])
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=owned.id, user_id=user.id, role="owner"))
    db_session.commit()

    token = create_access_token(user.id, module.settings.auth_secret_key, 5)
    with pytest.raises(HTTPException) as exc_info:
        module.require_context(
            make_request("GET", "/api/persons"),
            authorization=f"Bearer {token}",
            session_token=None,
            workspace_id_query=None,
            x_workspace_id=forbidden.id,
            db=db_session,
        )
    assert exc_info.value.status_code == 403


def test_require_context_accepts_session_cookie_for_read_requests(db_session: Session) -> None:
    module = load_test_main()
    user = User(username="cookie-reader", display_name="Cookie 用户", password_hash="unused")
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(name="Cookie 空间", kind="private", owner_user_id=user.id)
    db_session.add(workspace)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db_session.commit()

    token = create_access_token(user.id, module.settings.auth_secret_key, 5)
    current = module.require_context(
        make_request("GET", "/api/gallery/photos/1/original"),
        authorization=None,
        session_token=token,
        workspace_id_query=workspace.id,
        x_workspace_id=None,
        db=db_session,
    )

    assert current.user.id == user.id
    assert current.workspace_id == workspace.id


def test_require_context_rejects_session_cookie_for_write_requests(db_session: Session) -> None:
    module = load_test_main()
    user = User(username="cookie-writer", display_name="Cookie 写入用户", password_hash="unused")
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(name="Cookie 写入空间", kind="private", owner_user_id=user.id)
    db_session.add(workspace)
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db_session.commit()

    token = create_access_token(user.id, module.settings.auth_secret_key, 5)
    with pytest.raises(HTTPException) as exc_info:
        module.require_context(
            make_request("DELETE", "/api/gallery/photos/1"),
            authorization=None,
            session_token=token,
            workspace_id_query=workspace.id,
            x_workspace_id=None,
            db=db_session,
        )

    assert exc_info.value.status_code == 401


def test_auth_cookie_is_http_only_and_query_token_is_not_documented() -> None:
    module = load_test_main()
    response = Response()
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/login", "headers": [], "app": module.app})
    from app.api.system import _set_auth_cookie

    _set_auth_cookie(request, response, "test-token")

    cookie = response.headers["set-cookie"]
    assert f"{module.AUTH_COOKIE_NAME}=test-token" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api" in cookie

    schema = module.app.openapi()
    assert "/api/auth/logout" in schema["paths"]
    for path in schema["paths"].values():
        for operation in path.values():
            parameters = operation.get("parameters", [])
            assert all(parameter.get("name") != "access_token" for parameter in parameters)
