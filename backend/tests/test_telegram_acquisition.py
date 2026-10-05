from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet
from telethon.errors import FloodWaitError, PhoneNumberInvalidError
from telethon.tl.types.auth import SentCodeTypeApp, SentCodeTypeSms

from app.core.config import Settings
from app.services.acquisition_adapters.registry import get_script
from app.services.telegram import (
    TelegramRunAborted,
    TelegramService,
    code_delivery_from_type,
    extract_hashtags,
    media_matches,
    message_media_suffix,
    message_media_type,
    normalize_phone_number,
    scan_iter_kwargs,
    select_matching_media_groups,
    translate_telegram_error,
    video_metadata,
)


def _photo(
    message_id: int,
    published_at: datetime,
    *,
    grouped_id: int | None = None,
    caption: str = "",
    noforwards: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        date=published_at,
        grouped_id=grouped_id,
        message=caption,
        photo=object(),
        video=None,
        media=True,
        noforwards=noforwards,
        edit_date=None,
    )


def _text(message_id: int, published_at: datetime, caption: str = "纯文本") -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        date=published_at,
        grouped_id=None,
        message=caption,
        photo=None,
        video=None,
        media=None,
        noforwards=False,
        edit_date=None,
    )


class TelegramAcquisitionTests(unittest.TestCase):
    def _collect_with_comments(self, roots, comments, parameters):
        service = TelegramService(Settings(telegram_session_encryption_key=Fernet.generate_key().decode("ascii")))
        channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=False)
        downloaded_ids = []
        scanned_threads = []

        class FakeClient:
            async def connect(self):
                pass

            async def is_user_authorized(self):
                return True

            async def iter_messages(self, _channel, **kwargs):
                if "reply_to" in kwargs:
                    scanned_threads.append(kwargs["reply_to"])
                    for message in comments.get(kwargs["reply_to"], []):
                        yield message
                else:
                    for message in sorted(roots, key=lambda item: item.id, reverse=not kwargs["reverse"]):
                        yield message

            async def download_media(self, message, file):
                downloaded_ids.append(message.id)
                Path(file).write_bytes(b"media-bytes")
                return file

        account = SimpleNamespace(
            session_encrypted=service.encrypt(""), api_id=1, api_hash_encrypted=service.encrypt("hash"),
        )
        delivered = []
        with tempfile.TemporaryDirectory() as raw_dir, \
                patch("app.services.telegram.TelegramClient", return_value=FakeClient()), \
                patch.object(service, "_resolve_target", new=AsyncMock(return_value=channel)), \
                patch.object(service, "_close_client", new=AsyncMock()):
            records = service.read_channel_media(account, "demo", parameters, Path(raw_dir), on_records=delivered.extend)
        self.assertEqual(delivered, records)
        return records, downloaded_ids, scanned_threads

    def test_comments_only_skips_root_album_and_inherits_caption_and_tags(self) -> None:
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        roots = [_photo(1, published, grouped_id=8, caption="原帖 #旅行 #Tokyo"), _photo(2, published, grouped_id=8)]
        comment = _photo(101, published, caption="评论 #tokyo #人像")
        records, downloads, threads = self._collect_with_comments(roots, {1: [comment]}, {"comments_only": True})
        self.assertEqual(downloads, [101])
        self.assertEqual(threads, [1])
        self.assertEqual(records[0]["caption"], "原帖 #旅行 #Tokyo\n\n评论 #tokyo #人像")
        self.assertEqual(records[0]["hashtags"], [("旅行", "旅行"), ("Tokyo", "tokyo"), ("人像", "人像")])
        self.assertEqual(records[0]["root_channel_message_id"], 1)
        self.assertTrue(records[0]["is_comment"])
        self.assertEqual(records[0]["external_key"], "99:101:1")

    def test_comments_only_finds_text_and_different_media_roots(self) -> None:
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        for root in [_text(1, published, "文字原帖 #旅行"), _photo(1, published, caption="图片原帖 #旅行")]:
            with self.subTest(root=root.message):
                comment = _photo(101, published)
                comment.photo = None
                comment.video = SimpleNamespace(attributes=[])
                records, downloads, threads = self._collect_with_comments(
                    [root], {1: [comment, _photo(102, published)]},
                    {"comments_only": True, "media_types": ["video"], "hashtags": ["旅行"]},
                )
                self.assertEqual(downloads, [101])
                self.assertEqual(threads, [1])
                self.assertEqual(records[0]["media_type"], "video")
                self.assertEqual(records[0]["caption"], root.message)
                self.assertEqual(records[0]["hashtags"], [("旅行", "旅行")])

    def test_comments_only_respects_root_filters_dates_and_limit(self) -> None:
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        roots = [
            _text(5, published + timedelta(days=1), "范围外 #旅行"),
            _text(4, published, "标签不匹配"),
            _text(3, published, "符合 #旅行"),
            _text(2, published, "符合 #旅行"),
            _text(1, published - timedelta(days=1), "范围外 #旅行"),
        ]
        comments = {item.id: [_photo(100 + item.id, published)] for item in roots}
        records, downloads, threads = self._collect_with_comments(roots, comments, {
            "comments_only": True, "hashtags": ["旅行"], "caption_keywords": ["符合"],
            "date_from": "2026-09-02T00:00:00+00:00", "date_to": "2026-09-02T23:59:59+00:00",
            "max_messages": 1,
        })
        self.assertEqual(downloads, [103])
        self.assertEqual(threads, [3])
        self.assertEqual(len(records), 1)

    def test_comments_only_without_media_does_not_fall_back_to_root_download(self) -> None:
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        records, downloads, threads = self._collect_with_comments(
            [_photo(1, published, caption="原帖")], {1: [_text(101, published)]}, {"comments_only": True},
        )
        self.assertEqual(records, [])
        self.assertEqual(downloads, [])
        self.assertEqual(threads, [1])

    def test_existing_root_and_comment_collection_behavior_is_preserved(self) -> None:
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        for collect_comments, expected_downloads in [(False, [1]), (True, [1, 101])]:
            with self.subTest(collect_comments=collect_comments):
                records, downloads, threads = self._collect_with_comments(
                    [_photo(1, published, caption="原帖 #旅行")], {1: [_photo(101, published, caption="评论 #人像")]},
                    {"collect_comments": collect_comments},
                )
                self.assertEqual(downloads, expected_downloads)
                self.assertEqual(threads, [1] if collect_comments else [])
                self.assertEqual(records[-1]["caption"], "评论 #人像" if collect_comments else "原帖 #旅行")

    def test_comments_only_parameter_defaults_and_validation(self) -> None:
        definition = get_script("telegram-channel-mtproto")
        assert definition is not None
        self.assertFalse(definition.validate_parameters({})["comments_only"])
        parameters = definition.validate_parameters({"comments_only": True, "collect_comments": False})
        self.assertTrue(parameters["comments_only"])
        self.assertTrue(parameters["collect_comments"])
        with self.assertRaisesRegex(ValueError, "必须是布尔值"):
            definition.validate_parameters({"comments_only": "true"})

    def test_video_metadata_reads_document_attributes(self) -> None:
        message = SimpleNamespace(video=SimpleNamespace(attributes=[SimpleNamespace(duration=12, w=1920, h=1080)]))
        self.assertEqual(video_metadata(message), (12.0, 1920, 1080))
        self.assertEqual(video_metadata(SimpleNamespace(video=None)), (None, None, None))

    def test_document_media_is_classified_by_mime_type_and_filename(self) -> None:
        image = SimpleNamespace(
            document=SimpleNamespace(mime_type="application/octet-stream", attributes=[]),
            file=SimpleNamespace(name="portrait.JPG", mime_type="application/octet-stream"),
            photo=None,
            video=None,
        )
        video = SimpleNamespace(
            document=SimpleNamespace(
                mime_type="video/mp4",
                attributes=[SimpleNamespace(duration=12, w=1920, h=1080)],
            ),
            file=SimpleNamespace(name="clip", mime_type="video/mp4"),
            photo=None,
            video=None,
        )
        pdf = SimpleNamespace(
            document=SimpleNamespace(mime_type="application/pdf", attributes=[]),
            file=SimpleNamespace(name="notes.pdf", mime_type="application/pdf"),
            photo=None,
            video=None,
        )

        self.assertEqual(message_media_type(image), "image")
        self.assertEqual(message_media_suffix(image, "image"), ".jpg")
        self.assertEqual(message_media_type(video), "video")
        self.assertEqual(message_media_suffix(video, "video"), ".mp4")
        self.assertEqual(video_metadata(video), (12.0, 1920, 1080))
        self.assertIsNone(message_media_type(pdf))

    def test_extract_hashtags_deduplicates_normalized_values(self) -> None:
        tags = extract_hashtags("#旅行 今天的 #旅行 #Tokyo")
        self.assertEqual(tags, [("旅行", "旅行"), ("Tokyo", "tokyo")])

    def test_media_filters_require_every_tag_and_keyword(self) -> None:
        published = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
        tags = extract_hashtags("东京旅行 #旅行 #Tokyo")
        self.assertTrue(media_matches(
            published_at=published,
            media_type="image",
            caption="东京旅行 #旅行 #Tokyo",
            hashtags=tags,
            date_from=datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc),
            date_to=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
            allowed_media_types={"image"},
            required_hashtags=["旅行", "#tokyo"],
            required_keywords=["东京", "旅行"],
        ))
        self.assertFalse(media_matches(
            published_at=published,
            media_type="image",
            caption="东京旅行 #旅行 #Tokyo",
            hashtags=tags,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=["缺失"],
            required_keywords=["东京"],
        ))

    def test_normalize_phone_number_accepts_domestic_and_e164(self) -> None:
        self.assertEqual(normalize_phone_number("13812345678"), "+8613812345678")
        self.assertEqual(normalize_phone_number("+86 138-1234-5678"), "+8613812345678")
        self.assertEqual(normalize_phone_number("8613812345678"), "+8613812345678")
        self.assertEqual(normalize_phone_number("１３８１２３４５６７８"), "+8613812345678")
        with self.assertRaisesRegex(ValueError, "国家区号"):
            normalize_phone_number("12345678")

    def test_code_delivery_and_error_translation(self) -> None:
        self.assertEqual(code_delivery_from_type(SentCodeTypeApp(length=5)), "app")
        self.assertEqual(code_delivery_from_type(SentCodeTypeSms(length=5)), "sms")
        self.assertIn("频繁", translate_telegram_error(FloodWaitError(request=None, capture=12)))
        self.assertIn("手机号无效", translate_telegram_error(PhoneNumberInvalidError(request=None)))
        self.assertIn(
            "公开频道",
            translate_telegram_error(ValueError("Could not find the input entity for PeerChannel(channel_id=2653573634) (PeerChannel).")),
        )

    def test_start_login_persists_session_in_pending_state(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        login_result = SimpleNamespace(
            phone_code_hash="hash-1",
            phone_number="+8613812345678",
            session="session-string-1",
            code_delivery="app",
        )

        async def fake_start(api_id, api_hash, phone):
            return login_result

        with patch.object(service, "_start_login_async", side_effect=fake_start):
            account = service.start_login(None, workspace_id=7, api_id=12345, api_hash="x" * 32, phone="13812345678")
        self.assertEqual(account.status, "verification_pending")
        self.assertEqual(account.api_id, 12345)
        pending = service._decode_pending(account.pending_login_state_encrypted)
        self.assertEqual(pending["phone_number"], "+8613812345678")
        self.assertEqual(pending["phone_code_hash"], "hash-1")
        self.assertEqual(pending["session"], "session-string-1")
        self.assertEqual(pending["code_delivery"], "app")
        self.assertEqual(service.read_pending_code_delivery(account), "app")

    def test_verify_login_reuses_pending_session(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        account = SimpleNamespace(
            api_id=12345,
            api_hash_encrypted=service.encrypt("h" * 32),
            pending_login_state_encrypted=service._encode_pending(
                phone_number="+8613812345678",
                phone_code_hash="hash-1",
                session="pending-session",
                code_delivery="sms",
            ),
            session_encrypted=None,
            telegram_user_id=None,
            username=None,
            status="verification_pending",
            last_login_at=None,
        )
        captured: dict[str, object] = {}

        async def fake_verify(api_id, api_hash, phone, code_hash, code, password, session_string):
            captured.update(
                {
                    "api_id": api_id,
                    "phone": phone,
                    "code_hash": code_hash,
                    "code": code,
                    "session_string": session_string,
                }
            )
            return "final-session", 99, "demo_user"

        with patch.object(service, "_verify_login_async", side_effect=fake_verify):
            service.verify_login(account, "12345", None)
        self.assertEqual(account.status, "active")
        self.assertEqual(account.telegram_user_id, 99)
        self.assertEqual(account.username, "demo_user")
        self.assertIsNone(account.pending_login_state_encrypted)
        self.assertEqual(service.decrypt(account.session_encrypted), "final-session")
        self.assertEqual(captured["session_string"], "pending-session")
        self.assertEqual(captured["phone"], "+8613812345678")
        self.assertEqual(captured["code_hash"], "hash-1")

    def test_resend_login_reuses_pending_session(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        account = SimpleNamespace(
            api_id=12345,
            api_hash_encrypted=service.encrypt("h" * 32),
            pending_login_state_encrypted=service._encode_pending(
                phone_number="+8613812345678",
                phone_code_hash="hash-1",
                session="pending-session",
                code_delivery="app",
            ),
            session_encrypted=None,
            status="verification_pending",
            phone_masked=None,
        )
        captured: dict[str, object] = {}

        async def fake_start(api_id, api_hash, phone, session_string=""):
            captured.update({"phone": phone, "session_string": session_string})
            return SimpleNamespace(
                phone_code_hash="hash-2",
                phone_number=phone,
                session="session-2",
                code_delivery="app",
            )

        with patch.object(service, "_start_login_async", side_effect=fake_start):
            service.resend_login_code(account)
        self.assertEqual(captured["session_string"], "pending-session")
        self.assertEqual(captured["phone"], "+8613812345678")
        self.assertEqual(account.status, "verification_pending")

    def test_parse_datetime_treats_naive_values_as_shanghai(self) -> None:
        naive = TelegramService._parse_datetime("2026-09-02T00:00")
        explicit = TelegramService._parse_datetime("2026-09-02T00:00:00+08:00")
        self.assertEqual(naive, datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(explicit, naive)

    def test_scan_iter_kwargs_use_exclusive_offset_dates(self) -> None:
        date_from = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
        date_to = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        newest = scan_iter_kwargs(newest_first=True, date_from=date_from, date_to=date_to)
        oldest = scan_iter_kwargs(newest_first=False, date_from=date_from, date_to=date_to)
        self.assertEqual(newest["reverse"], False)
        self.assertEqual(newest["offset_date"], date_to + timedelta(microseconds=1))
        self.assertEqual(oldest["reverse"], True)
        self.assertEqual(oldest["offset_date"], date_from - timedelta(microseconds=1))

    def test_shanghai_morning_messages_match_today_range(self) -> None:
        # Shanghai 2026-09-02 01:00 == UTC 2026-09-01 17:00
        message = _photo(10, datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc), caption="今日")
        date_from = TelegramService._parse_datetime("2026-09-02T00:00")
        date_to = TelegramService._parse_datetime("2026-09-02T12:00")
        groups = select_matching_media_groups(
            [message],
            date_from=date_from,
            date_to=date_to,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=10,
            newest_first=True,
        )
        self.assertEqual([[item.id for item in group] for group in groups], [[10]])

    def test_max_messages_counts_albums_not_photos_newest_first(self) -> None:
        newer = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        older = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
        album_a = [
            _photo(109 - index, newer, grouped_id=1001, caption="最新相册" if index == 8 else "")
            for index in range(9)
        ]
        album_b = [
            _photo(99 - index, older, grouped_id=1002, caption="第二新" if index == 9 else "")
            for index in range(10)
        ]
        # Newest-first stream: album A photos then album B photos.
        stream = album_a + album_b
        groups = select_matching_media_groups(
            stream,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=2,
            newest_first=True,
        )
        self.assertEqual(len(groups), 2)
        self.assertEqual([item.id for item in groups[0]], list(range(101, 110)))
        self.assertEqual([item.id for item in groups[1]], list(range(90, 100)))
        self.assertEqual(sum(len(group) for group in groups), 19)

    def test_max_messages_counts_albums_oldest_first(self) -> None:
        older = datetime(2026, 9, 2, 7, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        album_old = [_photo(90 + index, older, grouped_id=1, caption="旧相册" if index == 0 else "") for index in range(3)]
        album_new = [_photo(100 + index, newer, grouped_id=2, caption="新相册" if index == 0 else "") for index in range(4)]
        stream = album_old + album_new
        groups = select_matching_media_groups(
            stream,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=1,
            newest_first=False,
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual([item.id for item in groups[0]], [90, 91, 92])

    def test_date_window_stops_and_skips_outside_messages(self) -> None:
        inside = datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc)
        too_new = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
        too_old = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        date_from = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        date_to = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)
        newest_stream = [
            _photo(3, too_new),
            _photo(2, inside),
            _photo(1, too_old),
        ]
        newest_groups = select_matching_media_groups(
            newest_stream,
            date_from=date_from,
            date_to=date_to,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=10,
            newest_first=True,
        )
        self.assertEqual([[item.id for item in group] for group in newest_groups], [[2]])

        oldest_stream = [
            _photo(1, too_old),
            _photo(2, inside),
            _photo(3, too_new),
        ]
        oldest_groups = select_matching_media_groups(
            oldest_stream,
            date_from=date_from,
            date_to=date_to,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=10,
            newest_first=False,
        )
        self.assertEqual([[item.id for item in group] for group in oldest_groups], [[2]])

    def test_album_caption_applies_to_whole_group(self) -> None:
        published = datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)
        # Newest-first: caption sits on the oldest/lowest id.
        stream = [
            _photo(12, published, grouped_id=7, caption=""),
            _photo(11, published, grouped_id=7, caption=""),
            _photo(10, published, grouped_id=7, caption="封面 #旅行"),
            _photo(9, published, caption="无关"),
        ]
        matched = select_matching_media_groups(
            stream,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=["旅行"],
            required_keywords=[],
            max_messages=10,
            newest_first=True,
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual([item.id for item in matched[0]], [10, 11, 12])

        skipped = select_matching_media_groups(
            stream,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=["缺失"],
            required_keywords=[],
            max_messages=10,
            newest_first=True,
        )
        self.assertEqual(skipped, [])

    def test_text_messages_do_not_consume_message_limit(self) -> None:
        published = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)
        stream = [
            _text(30, published),
            _photo(29, published),
            _text(28, published),
            _photo(27, published),
        ]
        groups = select_matching_media_groups(
            stream,
            date_from=None,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=1,
            newest_first=True,
        )
        self.assertEqual([[item.id for item in group] for group in groups], [[29]])

    def test_telegram_script_exposes_scan_order_and_shanghai_labels(self) -> None:
        definition = get_script("telegram-channel-mtproto")
        assert definition is not None
        self.assertEqual(definition.version, "1.1.0")
        keys = [parameter.key for parameter in definition.parameters]
        self.assertIn("scan_order", keys)
        validated = definition.validate_parameters({})
        self.assertEqual(validated["scan_order"], "newest")
        self.assertEqual(validated["max_messages"], 1000)
        date_from = next(parameter for parameter in definition.parameters if parameter.key == "date_from")
        self.assertIn("上海", date_from.label)

    def test_album_completed_across_date_boundary(self) -> None:
        in_range = datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc)
        out_of_range = datetime(2026, 9, 1, 23, 0, tzinfo=timezone.utc)
        date_from = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
        # Newest-first: newer album photos first, then older photo of same album past date_from.
        stream = [
            _photo(12, in_range, grouped_id=5, caption=""),
            _photo(11, in_range, grouped_id=5, caption=""),
            _photo(10, out_of_range, grouped_id=5, caption="跨边界"),
            _photo(9, out_of_range, caption="更旧"),
        ]
        groups = select_matching_media_groups(
            stream,
            date_from=date_from,
            date_to=None,
            allowed_media_types={"image"},
            required_hashtags=[],
            required_keywords=[],
            max_messages=10,
            newest_first=True,
        )
        self.assertEqual([[item.id for item in group] for group in groups], [[10, 11, 12]])

    def test_download_group_skips_failed_media_and_keeps_the_rest(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(
            Settings(telegram_session_encryption_key=key, telegram_download_timeout_seconds=2)
        )
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        messages = [
            _photo(1, published, grouped_id=8, caption="相册"),
            _photo(2, published, grouped_id=8),
            _photo(3, published, grouped_id=8),
        ]
        channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=False)

        class FakeClient:
            async def download_media(self, message, file):
                if message.id == 2:
                    raise ConnectionError("connection closed")
                Path(file).write_bytes(b"image-bytes")
                return file

        async def no_sleep(_seconds):
            return None

        with tempfile.TemporaryDirectory() as raw_dir, patch("app.services.telegram.asyncio.sleep", side_effect=no_sleep):
            records = asyncio.run(service._download_media_group(FakeClient(), channel, messages, Path(raw_dir)))
        self.assertEqual([record["message_id"] for record in records], [1, 3])
        self.assertTrue(all(record["caption"] == "相册" for record in records))

    def test_download_group_fetches_noforwards_media(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(
            Settings(telegram_session_encryption_key=key, telegram_download_timeout_seconds=2)
        )
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        channel_messages = [_photo(1, published, caption="频道保护")]
        message_protected = [_photo(2, published, noforwards=True, caption="单条保护")]
        protected_channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=True)
        open_channel = SimpleNamespace(id=100, title="公开", username="open", noforwards=False)
        downloaded_ids: list[int] = []

        class FakeClient:
            async def download_media(self, message, file):
                downloaded_ids.append(message.id)
                Path(file).write_bytes(b"image-bytes")
                return file

        client = FakeClient()
        with tempfile.TemporaryDirectory() as raw_dir:
            target = Path(raw_dir)
            channel_records = asyncio.run(service._download_media_group(client, protected_channel, channel_messages, target))
            message_records = asyncio.run(service._download_media_group(client, open_channel, message_protected, target))
            self.assertEqual(downloaded_ids, [1, 2])
            self.assertEqual(len(channel_records), 1)
            self.assertTrue(channel_records[0]["protected_content"])
            self.assertTrue(channel_records[0]["path"].is_file())
            self.assertEqual(len(message_records), 1)
            self.assertTrue(message_records[0]["protected_content"])
            self.assertTrue(message_records[0]["path"].is_file())

    def test_download_group_marks_protected_when_noforwards_download_fails(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(
            Settings(telegram_session_encryption_key=key, telegram_download_timeout_seconds=2)
        )
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        messages = [_photo(1, published, caption="保护失败")]
        channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=True)

        class FakeClient:
            async def download_media(self, message, file):
                raise ConnectionError("connection closed")

        async def no_sleep(_seconds):
            return None

        with tempfile.TemporaryDirectory() as raw_dir, patch("app.services.telegram.asyncio.sleep", side_effect=no_sleep):
            records = asyncio.run(service._download_media_group(FakeClient(), channel, messages, Path(raw_dir)))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["message_id"], 1)
        self.assertTrue(records[0]["protected_content"])
        self.assertIsNone(records[0]["path"])

    def test_collection_client_limits_internal_request_retries(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        seen: dict[str, object] = {}

        class FakeTelegramClient:
            def __init__(self, session: object, api_id: int, api_hash: str, **kwargs: object) -> None:
                seen["request_retries"] = kwargs.get("request_retries")
                seen["receive_updates"] = kwargs.get("receive_updates")
                seen["timeout"] = kwargs.get("timeout")

            async def connect(self) -> None:
                raise RuntimeError("停止于连接")

        account = SimpleNamespace(
            session_encrypted=service.encrypt(""),
            api_id=1,
            api_hash_encrypted=service.encrypt("hash"),
        )
        with patch("app.services.telegram.TelegramClient", FakeTelegramClient):
            with self.assertRaisesRegex(ValueError, "停止于连接"):
                service.read_channel_media(account, "demo", {}, Path("."))
        self.assertEqual(seen["request_retries"], 2)
        self.assertEqual(seen["receive_updates"], False)
        self.assertEqual(seen["timeout"], 60)

    def test_download_group_stops_before_later_media(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key, telegram_download_timeout_seconds=2))
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        messages = [_photo(1, published, grouped_id=8), _photo(2, published, grouped_id=8), _photo(3, published, grouped_id=8)]
        channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=False)
        abort = threading.Event()
        calls: list[int] = []

        class FakeClient:
            async def download_media(self, message, file):
                calls.append(message.id)
                if message.id == 2:
                    abort.set()
                    await asyncio.sleep(30)
                Path(file).write_bytes(b"image-bytes")
                return file

        with tempfile.TemporaryDirectory() as raw_dir:
            with self.assertRaises(TelegramRunAborted):
                asyncio.run(service._download_media_group(FakeClient(), channel, messages, Path(raw_dir), abort))
        self.assertEqual(calls, [1, 2])

    def test_file_stall_reconnects_and_backs_off(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key, telegram_download_timeout_seconds=2))
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        message = _photo(7, published)
        channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=False)

        for stall_factory in (
            lambda: ValueError("Request was unsuccessful 6 time(s)"),
            TimeoutError,
        ):
            stall = stall_factory()
            with self.subTest(stall=type(stall).__name__):
                sleeps: list[float] = []

                async def record_sleep(seconds: float) -> None:
                    sleeps.append(seconds)

                class FakeClient:
                    def __init__(self) -> None:
                        self.downloads = 0
                        self.reconnects = 0

                    async def download_media(self, downloaded_message, file):
                        self.downloads += 1
                        if self.downloads == 1:
                            raise stall
                        Path(file).write_bytes(b"image-bytes")
                        return file

                    async def disconnect(self) -> None:
                        self.reconnects += 1

                    async def connect(self) -> None:
                        return None

                    async def is_user_authorized(self) -> bool:
                        return True

                client = FakeClient()
                with tempfile.TemporaryDirectory() as raw_dir, patch("app.services.telegram.asyncio.sleep", side_effect=record_sleep):
                    records = asyncio.run(service._download_media_group(client, channel, [message], Path(raw_dir)))
                self.assertEqual([item["message_id"] for item in records], [7])
                self.assertEqual(client.reconnects, 1)
                self.assertEqual(sleeps, [15])

    def test_flood_wait_retries_without_reconnect(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key, telegram_download_timeout_seconds=2))
        published = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
        message = _photo(8, published)
        channel = SimpleNamespace(id=99, title="频道", username="demo", noforwards=False)
        sleeps: list[float] = []

        async def record_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        class FakeClient:
            def __init__(self) -> None:
                self.downloads = 0

            async def download_media(self, downloaded_message, file):
                self.downloads += 1
                if self.downloads == 1:
                    raise FloodWaitError(request=None, capture=4)
                Path(file).write_bytes(b"image-bytes")
                return file

        with tempfile.TemporaryDirectory() as raw_dir, patch("app.services.telegram.asyncio.sleep", side_effect=record_sleep):
            records = asyncio.run(service._download_media_group(FakeClient(), channel, [message], Path(raw_dir)))
        self.assertEqual([item["message_id"] for item in records], [8])
        self.assertEqual(sleeps, [4])

    def test_serialize_forum_topics_uses_fallback_title(self) -> None:
        topics = TelegramService._serialize_forum_topics(SimpleNamespace(topics=[
            SimpleNamespace(id=1, title="公告", closed=False, pinned=True, date=None),
            SimpleNamespace(id=2, title="", closed=True, pinned=False, date=None),
        ]))
        self.assertEqual(topics[0]["topic_id"], 1)
        self.assertEqual(topics[0]["title"], "公告")
        self.assertTrue(topics[0]["pinned"])
        self.assertEqual(topics[1]["title"], "未命名话题")
        self.assertTrue(topics[1]["closed"])

    def test_scan_forum_topics_requires_channel_ref(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        with self.assertRaisesRegex(ValueError, "请输入频道链接"):
            service.scan_forum_topics(SimpleNamespace(), "  ")

    def test_scan_forum_topics_lists_forum_topics(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        called = {"topics": False}

        class FakeClient:
            async def get_peer_id(self, entity):
                return -100555

            async def __call__(self, request):
                called["topics"] = True
                return SimpleNamespace(topics=[
                    SimpleNamespace(id=11, title="公告", closed=False, pinned=True, date=None),
                ])

            async def disconnect(self):
                return None

        forum = SimpleNamespace(title="测试论坛", username="testforum", megagroup=True, forum=True, bot=False)

        async def fake_open(_account):
            return FakeClient()

        async def fake_resolve(_client, channel_ref):
            self.assertIn(channel_ref, {"@testforum", "https://t.me/testforum", "testforum"})
            return forum

        with patch.object(service, "_open_client", side_effect=fake_open), patch.object(
            TelegramService, "_resolve_channel", side_effect=fake_resolve
        ):
            result = service.scan_forum_topics(SimpleNamespace(), "https://t.me/testforum")
        self.assertTrue(result["is_forum"])
        self.assertEqual(result["peer_id"], "-100555")
        self.assertEqual(result["title"], "测试论坛")
        self.assertEqual(result["username"], "testforum")
        self.assertEqual(result["topics"][0]["topic_id"], 11)
        self.assertTrue(called["topics"])

    def test_scan_forum_topics_returns_empty_when_not_forum(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        called = {"topics": False}

        class FakeClient:
            async def get_peer_id(self, entity):
                return -100777

            async def __call__(self, request):
                called["topics"] = True
                raise AssertionError("非论坛频道不应请求话题列表")

            async def disconnect(self):
                return None

        channel = SimpleNamespace(title="普通频道", username="plain", megagroup=False, forum=False, bot=False)

        async def fake_open(_account):
            return FakeClient()

        async def fake_resolve(_client, _channel_ref):
            return channel

        with patch.object(service, "_open_client", side_effect=fake_open), patch.object(
            TelegramService, "_resolve_channel", side_effect=fake_resolve
        ):
            result = service.scan_forum_topics(SimpleNamespace(), "@plain")
        self.assertFalse(result["is_forum"])
        self.assertEqual(result["title"], "普通频道")
        self.assertEqual(result["topics"], [])
        self.assertFalse(called["topics"])

    def test_resolve_candidates_prefer_username_over_peer_id(self) -> None:
        candidates = TelegramService._resolve_candidates(
            "https://t.me/public/12",
            peer_id="-1002653573634",
            username="public",
        )
        self.assertEqual(candidates[0], "@public")
        self.assertIn("https://t.me/public/12", candidates)
        self.assertEqual(candidates[-1], "-1002653573634")
        self.assertEqual(TelegramService._public_ref_lookup("https://t.me/c/2653573634/8"), "-1002653573634")
        self.assertEqual(TelegramService._peer_id_aliases("2653573634"), {"2653573634", "-1002653573634"})

    def test_resolve_target_falls_back_from_peer_id_to_username(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        seen: list[str] = []
        channel = SimpleNamespace(id=2653573634, title="公开频道", username="public")

        async def fake_resolve(_client, candidate):
            seen.append(candidate)
            if candidate in {"@public", "public"}:
                return channel
            raise ValueError("Could not find the input entity for PeerChannel(channel_id=2653573634) (PeerChannel).")

        with patch.object(TelegramService, "_resolve_channel", side_effect=fake_resolve):
            result = asyncio.run(service._resolve_target(
                SimpleNamespace(),
                channel_ref="https://t.me/public",
                peer_id="-1002653573634",
                username="public",
            ))
        self.assertIs(result, channel)
        self.assertEqual(seen[0], "@public")

    def test_resolve_target_finds_joined_private_channel_in_dialogs(self) -> None:
        key = Fernet.generate_key().decode("ascii")
        service = TelegramService(Settings(telegram_session_encryption_key=key))
        entity = SimpleNamespace(id=2653573634, title="私有频道", username=None)

        class FakeClient:
            async def get_peer_id(self, item):
                return -1002653573634 if item is entity else 0

            async def iter_dialogs(self):
                yield SimpleNamespace(entity=entity)

        async def fake_resolve(_client, _candidate):
            raise ValueError("Could not find the input entity for PeerChannel(channel_id=2653573634) (PeerChannel).")

        with patch.object(TelegramService, "_resolve_channel", side_effect=fake_resolve):
            result = asyncio.run(service._resolve_target(
                FakeClient(),
                channel_ref="-1002653573634",
                peer_id="-1002653573634",
            ))
        self.assertIs(result, entity)
