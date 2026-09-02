from __future__ import annotations

from datetime import datetime
from io import BytesIO
from threading import Barrier, BoundedSemaphore, Lock, Thread
from types import SimpleNamespace

from PIL import Image

from app.api.acquisition import _asset_read, get_asset_preview
from app.models import AcquisitionAsset
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


def test_preview_endpoint_reads_source_without_persisting_derivative() -> None:
    payload = _static_image_bytes()
    asset = SimpleNamespace(
        id="asset-1",
        workspace_id=7,
        object_key="acquisition/photo.png",
        filename="photo.png",
        content_type="image/png",
    )

    class FakeStorage:
        def __init__(self) -> None:
            self.read_keys: list[str] = []

        def get_bytes(self, object_key: str) -> bytes:
            self.read_keys.append(object_key)
            return payload

    storage = FakeStorage()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(storage=storage)))
    )
    db = SimpleNamespace(get=lambda model, asset_id: asset if model is AcquisitionAsset and asset_id == asset.id else None)
    current = SimpleNamespace(workspace_id=7)

    response = get_asset_preview(
        "asset-1",
        request,
        max_edge=480,
        db=db,
        current=current,
    )

    assert storage.read_keys == ["acquisition/photo.png"]
    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    with Image.open(BytesIO(response.body)) as image:
        assert max(image.size) == 480


def test_preview_endpoint_limits_parallel_renders(monkeypatch) -> None:
    import app.api.acquisition as acquisition_api

    payload = _static_image_bytes()
    asset = SimpleNamespace(
        id="asset-1",
        workspace_id=7,
        object_key="acquisition/photo.png",
        filename="photo.png",
        content_type="image/png",
    )
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
            return original(source, max_edge)
        finally:
            with lock:
                current -= 1

    monkeypatch.setattr(acquisition_api, "_preview_render_slots", BoundedSemaphore(2))
    monkeypatch.setattr(acquisition_api, "render_acquisition_preview", counting_render)

    class FakeStorage:
        def get_bytes(self, _object_key: str) -> bytes:
            return payload

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(storage=FakeStorage())))
    )
    db = SimpleNamespace(get=lambda model, asset_id: asset if model is AcquisitionAsset and asset_id == asset.id else None)
    barrier = Barrier(4)

    def worker() -> None:
        barrier.wait()
        get_asset_preview("asset-1", request, max_edge=480, db=db, current=SimpleNamespace(workspace_id=7))

    threads = [Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert 1 <= peak <= 2
