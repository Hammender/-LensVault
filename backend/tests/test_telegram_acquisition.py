from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from telethon.errors import FloodWaitError, PhoneNumberInvalidError
from telethon.tl.types.auth import SentCodeTypeApp, SentCodeTypeSms

from app.core.config import Settings
from app.services.telegram import (
    TelegramService,
    code_delivery_from_type,
    extract_hashtags,
    media_matches,
    normalize_phone_number,
    translate_telegram_error,
)


class TelegramAcquisitionTests(unittest.TestCase):
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
