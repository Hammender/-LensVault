from __future__ import annotations

import subprocess
import threading
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.lifecycle import seed_acquisition_scripts
from app.models import AcquisitionRun, AcquisitionScript
from app.services.acquisition import AcquisitionService, _DownloadStartLimiter
from app.services.acquisition_adapters import (
    AccessBlockedError,
    IdolxxxGalleryAdapter,
    RemoteItem,
    RemotePage,
    _RequestStartLimiter,
    _request_bytes,
    curl_request_bytes,
    get_script,
    stable_key,
)


HTML_TYPE = "text/html; charset=utf-8"


def html(value: str) -> tuple[bytes, str]:
    return value.encode("utf-8"), HTML_TYPE


class IdolxxxAdapterTests(unittest.TestCase):
    def test_extracts_image_media_and_never_requests_premium_cards(self) -> None:
        listing = html(
            """
            <article class="post"><a href="/post/1/"><img alt="单图"></a></article>
            <article class="post post-premium"><a href="/post/99/">会员</a></article>
            <article class="post"><a href="/post/2/">多图</a></article>
            <article class="post"><a href="/post/3/">图加视频</a></article>
            <article class="post"><a href="/post/4/">纯视频</a></article>
            """
        )
        responses = {
            "https://gallery.example.test/idols/iu/": listing,
            "https://gallery.example.test/post/1/": html(
                """
                <div class="post-media">
                  <a class="post-media-item" href="https://media.gallery.example.test/files/src/a.jpg">
                    <img src="https://media.gallery.example.test/files/src/a.jpg">
                  </a>
                </div>
                """
            ),
            "https://gallery.example.test/post/2/": html(
                """
                <div class="post-media">
                  <a class="post-media-item" href="//media.gallery.example.test/files/src/b.jpg"><img src="/files/thumb/b.jpg"></a>
                  <a class="post-media-item" href="/files/thumb/c.jpg"><img data-src="//media.gallery.example.test/files/src/c.jpg"></a>
                  <a class="post-media-item" href="https://outside.test/files/src/no.jpg"><img src="https://outside.test/files/src/no.jpg"></a>
                </div>
                <div class="post-thumbs"><img src="/files/thumb/b.jpg"></div>
                """
            ),
            "https://gallery.example.test/post/3/": html(
                """
                <div class="post-media">
                  <a class="post-media-item" href="https://media.gallery.example.test/files/src/d.jpg"><img src="/files/thumb/d.jpg"></a>
                  <div class="post-media-item"><video poster="/files/thumb/video.jpg"><source type="video/mp4" data-src="//media.gallery.example.test/files/src/video.mp4"></video></div>
                </div>
                """
            ),
            "https://gallery.example.test/post/4/": html(
                """
                <div class="post-media"><div class="post-media-item"><video data-poster="/files/thumb/p.jpg"><source type="video/mp4" src="/files/src/v.mp4"></video></div></div>
                """
            ),
        }

        def request(url: str, *_args: object, **_kwargs: object) -> tuple[bytes, str]:
            return responses[url]

        with patch("app.services.acquisition_adapters._request_bytes", side_effect=request) as mocked:
            items = list(IdolxxxGalleryAdapter().enumerate("https://gallery.example.test/idols/iu/", {}, set(), False))

        originals = [item.candidate_urls[0] for item in items]
        self.assertEqual(
            originals,
            [
                "https://media.gallery.example.test/files/src/a.jpg",
                "https://media.gallery.example.test/files/src/b.jpg",
                "https://media.gallery.example.test/files/src/c.jpg",
                "https://media.gallery.example.test/files/src/d.jpg",
            ],
        )
        self.assertNotIn("https://gallery.example.test/post/99/", [call.args[0] for call in mocked.call_args_list])
        self.assertTrue(all(item.preview_url is None for item in items))
        self.assertTrue(all(item.source_url.startswith("https://gallery.example.test/post/") for item in items))
        self.assertTrue(all(item.referer_url == item.source_url for item in items))
        self.assertTrue(all(item.abort_on_access_block for item in items))
        self.assertEqual(items[0].external_key, stable_key(originals[0]))

    def test_scans_inclusive_page_range_and_limits_every_request_attempt(self) -> None:
        responses = {
            "https://gallery.example.test/idols/iu/": html(
                '<a href="/idols/iu/page/3/">3</a><article><a href="/post/1/">第一页</a></article>'
            ),
            "https://gallery.example.test/idols/iu/page/2/": html(
                '<article><a href="/post/2/">第二页</a></article>'
            ),
            "https://gallery.example.test/post/2/": html(
                '<div class="post-media"><a class="post-media-item" href="//media.gallery.example.test/files/src/two.jpg"><img></a></div>'
            ),
        }

        def request(url: str, *_args: object, **kwargs: object) -> tuple[bytes, str]:
            before_attempt = kwargs.get("before_attempt")
            assert callable(before_attempt)
            before_attempt()
            return responses[url]

        with patch("app.services.acquisition_adapters._request_bytes", side_effect=request) as mocked, patch.object(
            _RequestStartLimiter, "wait"
        ) as wait:
            pages = list(
                IdolxxxGalleryAdapter().enumerate_pages(
                    "https://gallery.example.test/idols/iu/page/3/",
                    {"start_page": 2, "end_page": 2},
                    set(),
                    False,
                )
            )

        self.assertEqual([page.page_number for page in pages], [2])
        self.assertEqual(pages[0].stop_reason, "requested_end")
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(wait.call_count, 3)
        self.assertNotIn("https://gallery.example.test/post/1/", [call.args[0] for call in mocked.call_args_list])

    def test_duplicate_original_url_is_emitted_once(self) -> None:
        listing = html(
            '<article><a href="/post/1/">一</a></article><article><a href="/post/2/">二</a></article>'
        )
        detail = html(
            '<div class="post-media"><a class="post-media-item" href="//media.gallery.example.test/files/src/same.jpg"><img></a></div>'
        )
        responses = {
            "https://gallery.example.test/idols/iu/": listing,
            "https://gallery.example.test/post/1/": detail,
            "https://gallery.example.test/post/2/": detail,
        }
        with patch(
            "app.services.acquisition_adapters._request_bytes", side_effect=lambda url, *_args, **_kwargs: responses[url]
        ):
            items = list(IdolxxxGalleryAdapter().enumerate("https://gallery.example.test/idols/iu/", {}, set(), False))

        self.assertEqual(len(items), 1)

    def test_page_parameters_are_validated(self) -> None:
        definition = get_script("idolxxx-gallery")
        assert definition is not None
        self.assertEqual(definition.validate_parameters({}), {"start_page": 1})
        self.assertEqual(
            definition.validate_parameters({"start_page": "2", "end_page": "4"}),
            {"start_page": 2, "end_page": 4},
        )
        with self.assertRaisesRegex(ValueError, "结束页不能小于起始页"):
            definition.validate_parameters({"start_page": 4, "end_page": 2})

    def test_urllib_403_is_not_retried(self) -> None:
        error = HTTPError("https://gallery.example.test/idols/iu/", 403, "Forbidden", None, None)
        with patch("app.services.acquisition_adapters.urlopen", side_effect=error) as mocked:
            with self.assertRaises(AccessBlockedError):
                _request_bytes(
                    "https://gallery.example.test/idols/iu/",
                    "text/html",
                    "https://gallery.example.test/idols/iu/",
                    abort_on_access_block=True,
                )
        self.assertEqual(mocked.call_count, 1)

    def test_temporary_html_request_error_uses_finite_retry_budget(self) -> None:
        class Response:
            headers = {"Content-Type": HTML_TYPE}

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return b"ok"

        with patch(
            "app.services.acquisition_adapters.urlopen",
            side_effect=[TimeoutError("temporary"), TimeoutError("temporary"), Response()],
        ) as mocked, patch("app.services.acquisition_adapters.time.sleep") as sleep:
            payload, content_type = _request_bytes(
                "https://gallery.example.test/idols/iu/",
                "text/html",
                "https://gallery.example.test/idols/iu/",
                abort_on_access_block=True,
                retries=3,
            )

        self.assertEqual(payload, b"ok")
        self.assertEqual(content_type, HTML_TYPE)
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_html_retries_use_the_request_start_limiter(self) -> None:
        class Response:
            headers = {"Content-Type": HTML_TYPE}

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return b"ok"

        before_attempt = Mock()
        with patch(
            "app.services.acquisition_adapters.urlopen",
            side_effect=[TimeoutError("temporary"), TimeoutError("temporary"), Response()],
        ) as mocked, patch("app.services.acquisition_adapters.time.sleep") as sleep:
            _request_bytes(
                "https://gallery.example.test/idols/iu/",
                "text/html",
                "https://gallery.example.test/idols/iu/",
                retries=3,
                before_attempt=before_attempt,
            )

        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(before_attempt.call_count, 3)
        sleep.assert_not_called()

    def test_detail_cards_are_fetched_two_at_a_time_and_emitted_in_small_batches(self) -> None:
        listing = html(
            "".join(f'<article><a href="/post/{index}/">卡片 {index}</a></article>' for index in range(1, 10))
        )
        active = 0
        peak_active = 0
        lock = threading.Lock()
        barrier = threading.Barrier(2, timeout=2)

        def request(url: str, *_args: object, **_kwargs: object) -> tuple[bytes, str]:
            nonlocal active, peak_active
            if "/post/" not in url:
                return listing
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                post_number = int(url.rstrip("/").rsplit("/", 1)[-1])
                if post_number != 9:
                    barrier.wait()
                return html(
                    '<div class="post-media">'
                    f'<a class="post-media-item" href="//media.gallery.example.test/files/src/{post_number}.jpg"><img></a>'
                    "</div>"
                )
            finally:
                with lock:
                    active -= 1

        with patch("app.services.acquisition_adapters._request_bytes", side_effect=request):
            pages = list(IdolxxxGalleryAdapter().enumerate_pages(
                "https://gallery.example.test/idols/iu/", {}, set(), False
            ))

        self.assertEqual(peak_active, 2)
        self.assertEqual([len(page.items) for page in pages], [4, 4, 1])
        self.assertEqual([page.page_number for page in pages], [1, 1, 1])
        self.assertEqual([page.stop_reason for page in pages], [None, None, "collection_end"])
        self.assertEqual(
            [item.candidate_urls[0] for page in pages for item in page.items],
            [f"https://media.gallery.example.test/files/src/{index}.jpg" for index in range(1, 10)],
        )

    def test_incremental_known_page_stops_only_after_the_final_batch(self) -> None:
        listing = html(
            '<a href="/idols/iu/page/2/">2</a>'
            + "".join(f'<article><a href="/post/{index}/">卡片 {index}</a></article>' for index in range(1, 6))
        )
        known_keys = {
            stable_key(f"https://media.gallery.example.test/files/src/{index}.jpg")
            for index in range(1, 6)
        }

        def request(url: str, *_args: object, **_kwargs: object) -> tuple[bytes, str]:
            if "/post/" not in url:
                return listing
            post_number = int(url.rstrip("/").rsplit("/", 1)[-1])
            return html(
                '<div class="post-media">'
                f'<a class="post-media-item" href="//media.gallery.example.test/files/src/{post_number}.jpg"><img></a>'
                "</div>"
            )

        with patch("app.services.acquisition_adapters._request_bytes", side_effect=request) as mocked:
            pages = list(IdolxxxGalleryAdapter().enumerate_pages(
                "https://gallery.example.test/idols/iu/", {}, known_keys, True
            ))

        self.assertEqual([len(page.items) for page in pages], [4, 1])
        self.assertEqual([page.stop_reason for page in pages], [None, "known_page"])
        self.assertNotIn(
            "https://gallery.example.test/idols/iu/page/2/",
            [call.args[0] for call in mocked.call_args_list],
        )

    def test_detail_access_block_does_not_start_the_next_request_group(self) -> None:
        listing = html(
            "".join(f'<article><a href="/post/{index}/">卡片 {index}</a></article>' for index in range(1, 5))
        )

        def request(url: str, *_args: object, **_kwargs: object) -> tuple[bytes, str]:
            if "/post/" not in url:
                return listing
            if url.endswith("/post/1/"):
                raise AccessBlockedError(url, 429)
            return html('<div class="post-media"></div>')

        with patch("app.services.acquisition_adapters._request_bytes", side_effect=request) as mocked:
            with self.assertRaises(AccessBlockedError):
                list(IdolxxxGalleryAdapter().enumerate_pages(
                    "https://gallery.example.test/idols/iu/", {}, set(), False
                ))

        requested_posts = [call.args[0] for call in mocked.call_args_list if "/post/" in call.args[0]]
        self.assertNotIn("https://gallery.example.test/post/3/", requested_posts)
        self.assertNotIn("https://gallery.example.test/post/4/", requested_posts)

    def test_curl_429_is_not_retried(self) -> None:
        completed = subprocess.CompletedProcess([], 22, stdout="429\ntext/html", stderr="Too Many Requests")
        with patch("app.services.acquisition_adapters.shutil.which", return_value="curl.exe"), patch(
            "app.services.acquisition_adapters.subprocess.run", return_value=completed
        ) as run:
            with self.assertRaises(AccessBlockedError):
                curl_request_bytes(
                    "https://gallery.example.test/idols/iu/",
                    "text/html",
                    "https://gallery.example.test/idols/iu/",
                    retries=3,
                    abort_on_access_block=True,
                )
        self.assertEqual(run.call_count, 1)

    def test_curl_retries_use_the_shared_download_start_limiter(self) -> None:
        attempts = [
            subprocess.CompletedProcess([], 22, stdout="500\ntext/html", stderr="Temporary"),
            subprocess.CompletedProcess([], 22, stdout="500\ntext/html", stderr="Temporary"),
            subprocess.CompletedProcess([], 0, stdout="200\nimage/jpeg", stderr=""),
        ]
        before_attempt = Mock()
        with patch("app.services.acquisition_adapters.shutil.which", return_value="curl.exe"), patch(
            "app.services.acquisition_adapters.subprocess.run", side_effect=attempts
        ), patch("app.services.acquisition_adapters.time.sleep") as sleep:
            _payload, content_type = curl_request_bytes(
                "https://media.gallery.example.test/files/src/a.jpg",
                "image/*",
                "https://gallery.example.test/post/1/",
                retries=3,
                abort_on_access_block=True,
                before_attempt=before_attempt,
            )

        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(before_attempt.call_count, 3)
        sleep.assert_not_called()


class IdolxxxDownloadPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.service = AcquisitionService(
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(acquisition_download_workers=8),
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _start_run(self) -> tuple[object, AcquisitionRun]:
        definition = get_script("idolxxx-gallery")
        assert definition is not None
        self.db.add(
            AcquisitionScript(
                key=definition.key,
                name=definition.name,
                version=definition.version,
                page_format_key=definition.page_format_key,
                parameter_schema_json="[]",
            )
        )
        self.db.commit()
        source = self.service.create_source(self.db, None, "目标站点", "https://gallery.example.test")
        self.service.bind_script(self.db, source, definition.key)
        category = self.service.create_category(
            self.db,
            source,
            "IU",
            "https://gallery.example.test/idols/iu/",
        )
        return definition, self.service.start_run(self.db, None, category, definition.key, "incremental", {})

    def test_target_download_concurrency_is_capped_at_three(self) -> None:
        definition, run = self._start_run()
        barrier = threading.Barrier(3, timeout=2)
        active = 0
        peak_active = 0
        lock = threading.Lock()

        def download(_remote: RemoteItem, _referer: str) -> object:
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            barrier.wait()
            with lock:
                active -= 1
            return object()

        remotes = tuple(
            RemoteItem(
                f"remote-{index}",
                f"https://gallery.example.test/post/{index}/",
                candidate_urls=(f"https://media.gallery.example.test/files/src/{index}.jpg",),
                abort_on_access_block=True,
            )
            for index in range(6)
        )
        with patch.object(
            definition.adapter,
            "enumerate_pages",
            return_value=[RemotePage(1, remotes, "collection_end")],
        ), patch.object(self.service, "_download_and_analyze", side_effect=download), patch.object(
            self.service, "_persist_downloaded_remote"
        ), patch.object(_DownloadStartLimiter, "wait"):
            self.service.process_run(self.db, run.id)

        self.db.refresh(run)
        self.assertEqual(peak_active, 3)
        self.assertEqual(run.status, "completed")

    def test_first_access_block_stops_queued_downloads(self) -> None:
        definition, run = self._start_run()
        remotes = tuple(
            RemoteItem(
                f"remote-{index}",
                f"https://gallery.example.test/post/{index}/",
                candidate_urls=(f"https://media.gallery.example.test/files/src/{index}.jpg",),
                abort_on_access_block=True,
            )
            for index in range(5)
        )
        calls = 0

        def blocked(remote: RemoteItem, _referer: str) -> object:
            nonlocal calls
            calls += 1
            raise AccessBlockedError(remote.candidate_urls[0], 429)

        with patch.object(
            definition.adapter,
            "enumerate_pages",
            return_value=[RemotePage(1, remotes, "collection_end")],
        ), patch.object(self.service, "_download_and_analyze", side_effect=blocked):
            self.service.process_run(self.db, run.id)

        self.db.refresh(run)
        self.assertEqual(calls, 1)
        self.assertEqual(run.status, "failed")
        self.assertIn("HTTP 429", run.error_message or "")

    def test_image_download_403_is_not_retried_but_other_errors_are(self) -> None:
        settings = SimpleNamespace(
            acquisition_download_retries=3,
            acquisition_download_timeout_seconds=1,
            acquisition_max_file_bytes=1024,
        )
        service = AcquisitionService(SimpleNamespace(), SimpleNamespace(), settings)
        blocked = HTTPError("https://media.gallery.example.test/files/src/a.jpg", 403, "Forbidden", None, None)
        with patch("app.services.acquisition.urlopen", side_effect=blocked) as request:
            with self.assertRaises(AccessBlockedError):
                service._download(
                    "https://media.gallery.example.test/files/src/a.jpg",
                    "https://gallery.example.test/post/1/",
                    abort_on_access_block=True,
                )
        self.assertEqual(request.call_count, 1)

        temporary = HTTPError("https://cdn.example.test/a.jpg", 500, "Temporary", None, None)
        with patch("app.services.acquisition.urlopen", side_effect=temporary) as request:
            with self.assertRaises(RuntimeError):
                service._download("https://cdn.example.test/a.jpg", "https://example.test/")
        self.assertEqual(request.call_count, 3)


class IdolxxxDownloadLimiterTests(unittest.TestCase):
    def test_html_limiter_waits_only_for_the_remaining_interval(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        limiter = _RequestStartLimiter(1.0, clock=lambda: now[0], sleeper=sleep)
        limiter.wait()
        now[0] = 0.4
        limiter.wait()
        now[0] = 3.0
        limiter.wait()

        self.assertEqual(sleeps, [0.6])

    def test_download_starts_are_spaced_by_one_second(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            now[0] += seconds

        limiter = _DownloadStartLimiter(1.0, clock=lambda: now[0], sleeper=sleep)
        limiter.wait()
        limiter.wait()
        limiter.wait()

        self.assertEqual(sleeps, [1.0, 1.0])


class IdolxxxLifecycleTests(unittest.TestCase):
    def test_lifecycle_sync_registers_target_adapter(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        seed_acquisition_scripts(engine)
        with Session(engine) as db:
            script = db.scalar(select(AcquisitionScript).where(AcquisitionScript.key == "idolxxx-gallery"))
            self.assertIsNotNone(script)
            assert script is not None
            self.assertEqual(script.version, "1.0.1")
            self.assertEqual(script.page_format_key, "idolxxx-gallery-v1")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
