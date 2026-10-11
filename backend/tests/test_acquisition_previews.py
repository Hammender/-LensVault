from __future__ import annotations

import asyncio
import time
from datetime import datetime
from io import BytesIO
from threading import Event, Lock
from types import SimpleNamespace

from PIL import Image

from app.api.acquisition import _asset_read, get_asset_preview
from app.models import AcquisitionAsset
from app.services.acquisition import AcquisitionService
from app.services.thumbnails import render_acquisition_preview


def _static_image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1600, 900), "#2e7d32").save(output, format="PNG")
    return output.getvalue()


def _animated_image_bytes() -> bytes:
    frames = [
        Image.new("RGBA", (1200, 800), "#d84315"),
        Image.new("RGBA", (1200, 800), "#1565c0"),
    ]
    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[120, 260],
        loop=0,
    )
    return output.getvalue()


def test_static_acquisition_preview_is_bounded_jpeg() -> None:
    preview = render_acquisition_preview(_static_image_bytes(), 480)

    assert preview.media_type == "image/jpeg"
    with Image.open(BytesIO(preview.payload)) as image:
        assert image.format == "JPEG"
        assert max(image.size) == 480


def test_animated_acquisition_list_preview_uses_first_frame() -> None:
    preview = render_acquisition_preview(_animated_image_bytes(), 480)

    assert preview.media_type == "image/jpeg"
    with Image.open(BytesIO(preview.payload)) as image:
        assert getattr(image, "n_frames", 1) == 1
        assert max(image.size) == 480


def test_asset_read_uses_separate_versioned_preview_and_original_urls() -> None:
    asset = AcquisitionAsset(
        id="asset-1",
        workspace_id=7,
        sha256="a" * 64,
        filename="photo.png",
        content_type="image/png",
        object_key="acquisition/photo.png",
        size_bytes=123,
        quality_warnings="[]",
        status="pending_review",
        created_at=datetime(2026, 8, 14, 12, 0, 0),
    )

    result = _asset_read(asset)

    assert result.preview_url == f"/api/acquisition/assets/asset-1/preview?v={'a' * 64}"
    assert result.original_url == f"/api/acquisition/assets/asset-1/original?v={'a' * 64}"


def test_preview_endpoint_caches_derivative_and_releases_database() -> None:
    payload = _static_image_bytes()
    asset = SimpleNamespace(
        id="asset-1",
        workspace_id=7,
        object_key="acquisition/photo.png",
        filename="photo.png",
        content_type="image/png",
        sha256="a" * 64,
    )

    class FakeStorage:
        def __init__(self) -> None:
            self.read_keys: list[str] = []
            self.cached: dict[str, bytes] = {}

        def get_bytes(self, object_key: str) -> bytes:
            self.read_keys.append(object_key)
            if object_key == asset.object_key:
                return payload
            return self.cached[object_key]

        def put_bytes(self, object_key: str, value: bytes, _media_type: str) -> None:
            self.cached[object_key] = value

        def stat_object(self, object_key: str) -> None:
            assert object_key == asset.object_key

    storage = FakeStorage()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(storage=storage)))
    )
    released = []
    db = SimpleNamespace(get=lambda model, asset_id: asset if model is AcquisitionAsset and asset_id == asset.id else None,
                         rollback=lambda: released.append(True))
    current = SimpleNamespace(workspace_id=7)

    async def check():
        first = await get_asset_preview("asset-1", request, max_edge=480, db=db, current=current)
        second = await get_asset_preview("asset-1", request, max_edge=480, db=db, current=current)
        return first, second

    response, cached_response = asyncio.run(check())

    assert storage.read_keys.count("acquisition/photo.png") == 1
    assert len(storage.cached) == 1
    assert len(released) == 2
    assert response.body == cached_response.body
    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    with Image.open(BytesIO(response.body)) as image:
        assert max(image.size) == 480


def test_preview_endpoint_limits_parallel_renders(monkeypatch) -> None:
    import app.api.acquisition as acquisition_api

    payload = _static_image_bytes()
    assets = {
        f"asset-{index}": SimpleNamespace(id=f"asset-{index}", workspace_id=7,
                                         object_key=f"acquisition/{index}.png", sha256=str(index) * 64,
                                         filename=f"{index}.png", content_type="image/png")
        for index in range(4)
    }
    current = 0
    peak = 0
    lock = Lock()
    original = render_acquisition_preview

    def counting_render(source: bytes, max_edge: int):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        try:
            time.sleep(0.02)
            return original(source, max_edge)
        finally:
            with lock:
                current -= 1

    monkeypatch.setattr(acquisition_api, "render_acquisition_preview", counting_render)

    class FakeStorage:
        def get_bytes(self, object_key: str) -> bytes:
            if object_key.startswith("derived/"):
                raise KeyError(object_key)
            return payload

        def put_bytes(self, *_args):
            pass

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(storage=FakeStorage())))
    )
    db = SimpleNamespace(get=lambda model, asset_id: assets.get(asset_id) if model is AcquisitionAsset else None,
                         rollback=lambda: None)

    async def check():
        return await asyncio.gather(*(get_asset_preview(asset_id, request, max_edge=480, db=db,
                                                        current=SimpleNamespace(workspace_id=7)) for asset_id in assets))

    asyncio.run(check())

    assert 1 <= peak <= 2


def test_acquisition_cleanup_during_render_leaves_no_cache(monkeypatch) -> None:
    import app.api.acquisition as acquisition_api

    source_key = "acquisition/photo.png"
    asset = SimpleNamespace(id="asset-race", workspace_id=7, object_key=source_key,
                            filename="photo.png", sha256="a" * 64,
                            media_type="image", preview_object_key=None, error_message=None)
    entered = Event()
    resume = Event()
    original_render = render_acquisition_preview

    def delayed_render(payload, edge):
        entered.set()
        assert resume.wait(2)
        return original_render(payload, edge)

    monkeypatch.setattr(acquisition_api, "render_acquisition_preview", delayed_render)

    class Storage:
        def __init__(self):
            self.objects = {source_key: _static_image_bytes()}

        def get_bytes(self, key):
            return self.objects[key]

        def stat_object(self, key):
            if key not in self.objects:
                raise KeyError(key)

        def put_bytes(self, key, payload, _media_type):
            self.objects[key] = payload

        def remove_object(self, key):
            self.objects.pop(key, None)

        def remove_prefix(self, prefix):
            for key in list(self.objects):
                if key.startswith(prefix):
                    del self.objects[key]

    storage = Storage()
    db = SimpleNamespace(get=lambda model, key: asset if model is AcquisitionAsset and key == asset.id else None,
                         rollback=lambda: None, commit=lambda: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(storage=storage))))

    async def run():
        task = asyncio.create_task(get_asset_preview(asset.id, request, max_edge=480, db=db,
                                                     current=SimpleNamespace(workspace_id=7)))
        assert await asyncio.to_thread(entered.wait, 2)
        cleanup_service = SimpleNamespace(storage=storage,
                                          _preview_key=lambda workspace_id, asset_id: f"cover/{asset_id}.jpg")
        AcquisitionService._cleanup_asset_object(cleanup_service, db, asset)
        resume.set()
        return await task

    response = asyncio.run(run())
    assert response.body
    assert storage.objects == {}
