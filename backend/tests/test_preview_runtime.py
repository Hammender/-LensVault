"""预览缓存、数据库连接释放及异步排队回归。"""

from __future__ import annotations

import asyncio
import time
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.api.gallery import get_gallery_animated_thumbnail, get_gallery_thumbnail
from app.models import GalleryPhoto
from app.services.preview_runtime import PreviewRuntime, preview_source_guard, put_preview_if_source_exists
from app.services.thumbnails import gallery_preview_cache_key, normalize_preview_edge


def _image(animated: bool = False) -> bytes:
    output = BytesIO()
    first = Image.new("RGB", (1200, 800), "red")
    if animated:
        second = Image.new("RGB", (1200, 800), "blue")
        first.save(output, format="GIF", save_all=True, append_images=[second], duration=100)
    else:
        first.save(output, format="JPEG")
    return output.getvalue()


class FakeStorage:
    def __init__(self, source: bytes, db):
        self.source = source
        self.db = db
        self.objects = {}
        self.reads = []
        self.available = True

    def get_bytes(self, key):
        assert self.db.released
        self.reads.append(key)
        if key == "gallery/source":
            if not self.available:
                raise KeyError(key)
            return self.source
        return self.objects[key][0]

    def get_bytes_with_type(self, key):
        assert self.db.released
        self.reads.append(key)
        return self.objects[key]

    def put_bytes(self, key, payload, media_type):
        self.objects[key] = payload, media_type

    def stat_object(self, key):
        if key != "gallery/source" or not self.available:
            raise KeyError(key)


def _request(animated=False):
    photo = SimpleNamespace(id=42, workspace_id=1, sha256="a" * 64,
                            object_key="gallery/source", content_type="image/gif" if animated else "image/jpeg")
    db = SimpleNamespace(released=False)
    db.get = lambda model, photo_id: photo if model is GalleryPhoto and photo_id == photo.id else None
    db.rollback = lambda: setattr(db, "released", True)
    storage = FakeStorage(_image(animated), db)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        services=SimpleNamespace(storage=storage), settings=SimpleNamespace(image_compute_thumbnail_parallel=2))))
    current = SimpleNamespace(workspace_id=1)
    return request, db, current, storage


def test_gallery_static_preview_is_cached_and_database_released():
    request, db, current, storage = _request()

    async def run():
        first = await get_gallery_thumbnail(42, request, width=480, db=db, current=current)
        second = await get_gallery_thumbnail(42, request, width=480, db=db, current=current)
        return first, second

    first, second = asyncio.run(run())
    assert first.media_type == "image/jpeg"
    assert first.body == second.body
    assert storage.reads.count("gallery/source") == 1
    assert first.headers["cache-control"].startswith("private")


def test_gallery_animated_preview_keeps_media_type_and_cache():
    request, db, current, storage = _request(animated=True)

    async def run():
        first = await get_gallery_animated_thumbnail(42, request, db=db, current=current)
        second = await get_gallery_animated_thumbnail(42, request, db=db, current=current)
        return first, second

    first, second = asyncio.run(run())
    assert first.media_type == second.media_type == "image/webp"
    assert first.body == second.body
    assert storage.reads.count("gallery/source") == 1
    with Image.open(BytesIO(second.body)) as result:
        assert result.n_frames == 2


def test_gallery_cache_key_separates_workspace_content_and_mode():
    base = gallery_preview_cache_key(1, 42, "a" * 64, "static", 480)
    assert len({base, gallery_preview_cache_key(2, 42, "a" * 64, "static", 480),
                gallery_preview_cache_key(1, 42, "b" * 64, "static", 480),
                gallery_preview_cache_key(1, 42, "a" * 64, "animated", 720)}) == 4


def test_gallery_preview_widths_share_finite_cache_bands():
    request, db, current, storage = _request()

    async def run():
        first = await get_gallery_thumbnail(42, request, width=481, db=db, current=current)
        second = await get_gallery_thumbnail(42, request, width=559, db=db, current=current)
        return first, second

    first, second = asyncio.run(run())
    assert first.body == second.body
    assert len(storage.objects) == 1
    assert next(iter(storage.objects)).endswith("-static-560.bin")
    assert normalize_preview_edge(1) == 160
    assert normalize_preview_edge(2048) == 2048


def test_cache_write_after_source_cleanup_is_skipped():
    class Storage:
        def __init__(self):
            self.objects = {"source": b"original"}

        def stat_object(self, key):
            if key not in self.objects:
                raise KeyError(key)

        def put_bytes(self, key, payload, _media_type):
            self.objects[key] = payload

    storage = Storage()
    with preview_source_guard("source"):
        del storage.objects["source"]
        storage.objects.pop("cache", None)
    assert not put_preview_if_source_exists(storage, "source", "cache", b"preview", "image/jpeg")
    assert storage.objects == {}


def test_gallery_cleanup_during_render_leaves_no_orphan_cache(monkeypatch):
    import app.api.gallery as gallery_api

    request, db, current, storage = _request()
    entered = Event()
    resume = Event()
    render = gallery_api.render_gallery_static_thumbnail

    def delayed_render(payload, edge):
        entered.set()
        assert resume.wait(2)
        return render(payload, edge)

    monkeypatch.setattr(gallery_api, "render_gallery_static_thumbnail", delayed_render)

    async def run():
        task = asyncio.create_task(get_gallery_thumbnail(42, request, width=480, db=db, current=current))
        assert await asyncio.to_thread(entered.wait, 2)
        with preview_source_guard("gallery/source"):
            storage.available = False
            storage.objects.clear()
        resume.set()
        return await task

    response = asyncio.run(run())
    assert response.body
    assert storage.objects == {}


def test_preview_queue_keeps_event_loop_responsive_and_merges_equal_keys():
    runtime = PreviewRuntime(2)
    active = 0
    peak = 0
    calls = 0

    def operation():
        nonlocal active, peak, calls
        active += 1
        peak = max(peak, active)
        calls += 1
        time.sleep(0.05)
        active -= 1
        return b"ok"

    async def run():
        tasks = [asyncio.create_task(runtime.run(f"image-{index}", operation)) for index in range(12)]
        tasks.extend(asyncio.create_task(runtime.run("image-0", operation)) for _ in range(3))
        await asyncio.sleep(0.01)
        assert any(not task.done() for task in tasks)
        assert (await asyncio.gather(*tasks)) == [b"ok"] * 15

    asyncio.run(run())
    assert calls == 12
    assert peak == 2


def test_cancelled_waiter_does_not_cancel_shared_preview():
    runtime = PreviewRuntime(1)

    async def run():
        first = asyncio.create_task(runtime.run("one", lambda: (time.sleep(0.03), b"ok")[1]))
        second = asyncio.create_task(runtime.run("one", lambda: b"wrong"))
        await asyncio.sleep(0.01)
        second.cancel()
        try:
            await second
        except asyncio.CancelledError:
            pass
        assert await first == b"ok"

    asyncio.run(run())
