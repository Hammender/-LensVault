from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    ChannelPrivateError,
    ChatForwardsRestrictedError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon import functions, types
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import ChatInviteAlready, DocumentAttributeVideo
from telethon.tl.types.auth import (
    SentCodeTypeApp,
    SentCodeTypeCall,
    SentCodeTypeFlashCall,
    SentCodeTypeMissedCall,
    SentCodeTypeSms,
)

from app.core.config import Settings
from app.core.timezones import SHANGHAI_TZ, as_shanghai_naive, shanghai_now
from app.models import TelegramAccount


HASHTAG_PATTERN = re.compile(r"(?<!\w)#([\w\u4e00-\u9fff-]+)", re.UNICODE)
PHONE_DIGITS_PATTERN = re.compile(r"[^\d+]")
LOGGER = logging.getLogger(__name__)
_MICROSECOND = timedelta(microseconds=1)
_ABORT_POLL_SECONDS = 0.25
_COLLECTION_REQUEST_RETRIES = 2
_COLLECTION_REQUEST_TIMEOUT = 60
_FILE_STALL_BACKOFF_SECONDS = (15, 30)
IMAGE_FILE_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".jxl",
    ".png", ".tif", ".tiff", ".webp",
}
VIDEO_FILE_EXTENSIONS = {
    ".3gp", ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg",
    ".ogv", ".ts", ".webm", ".wmv",
}


@dataclass(frozen=True)
class TelegramLoginStart:
    phone_code_hash: str
    phone_number: str
    session: str
    code_delivery: str


def _to_ascii_phone_chars(value: str) -> str:
    translated = []
    for char in value:
        code = ord(char)
        if 0xFF10 <= code <= 0xFF19:
            translated.append(chr(code - 0xFF10 + 48))
        elif char == "＋":
            translated.append("+")
        else:
            translated.append(char)
    return "".join(translated)


def normalize_phone_number(value: str) -> str:
    compact = PHONE_DIGITS_PATTERN.sub("", _to_ascii_phone_chars(value or "").strip())
    if not compact:
        raise ValueError("请输入手机号，例如 +86138xxxx 或 138xxxx")
    if compact.startswith("00"):
        compact = f"+{compact[2:]}"
    if compact.startswith("+"):
        digits = compact[1:]
        if not digits.isdigit() or len(digits) < 8 or len(digits) > 15:
            raise ValueError("国际手机号格式无效，请使用例如 +86138xxxx")
        if len(digits) == 11 and digits.startswith("1"):
            return f"+86{digits}"
        return f"+{digits}"
    if not compact.isdigit():
        raise ValueError("手机号只能包含数字和可选的 + 号，例如 +86138xxxx")
    if len(compact) == 11 and compact.startswith("1"):
        return f"+86{compact}"
    if compact.startswith("86") and 12 <= len(compact) <= 13:
        return f"+{compact}"
    if 8 <= len(compact) <= 15:
        raise ValueError("请填写含国家区号的手机号，例如 +86138xxxx")
    raise ValueError("手机号长度无效，请使用例如 +86138xxxx 或 11 位国内手机号")


def code_delivery_from_type(type_obj: object) -> str:
    if isinstance(type_obj, SentCodeTypeApp):
        return "app"
    if isinstance(type_obj, (SentCodeTypeSms,)):
        return "sms"
    if isinstance(type_obj, (SentCodeTypeCall, SentCodeTypeFlashCall, SentCodeTypeMissedCall)):
        return "call"
    return "unknown"


def delivery_hint(code_delivery: str | None) -> str:
    if code_delivery == "app":
        return "验证码已发到 Telegram App：打开与官方账号「Telegram」（777000）的对话，也可检查已登录的电脑端"
    if code_delivery == "sms":
        return "请查收手机短信中的登录验证码；国内号有时收不到短信，可改在 App 中查看"
    if code_delivery == "call":
        return "请留意来电或未接来电中的验证码"
    return "请打开 Telegram App 与官方账号「Telegram」（777000）的对话查看验证码，国内号通常不会发短信"


def translate_telegram_error(exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        message = str(exc)
        if "Could not find the input entity" in message:
            return (
                "当前登录账号无法定位该频道。公开频道请使用用户名或 t.me 公开链接，不必加入；"
                "私有频道必须先用该账号在 Telegram 里加入，再通过「选择已登录会话」或邀请链接添加。"
            )
        return message
    if isinstance(exc, FloodWaitError):
        return f"Telegram 请求过于频繁，请等待 {exc.seconds} 秒后再试"
    if isinstance(exc, PhoneNumberInvalidError):
        return "手机号无效，请确认已填写正确的国家区号，例如 +86138xxxx"
    if isinstance(exc, PhoneNumberBannedError):
        return "该手机号已被 Telegram 限制登录"
    if isinstance(exc, PhoneNumberFloodError):
        return "该手机号发送验证码过于频繁，请稍后再试"
    if isinstance(exc, PhoneCodeInvalidError):
        return "验证码错误，请重新输入"
    if isinstance(exc, PhoneCodeExpiredError):
        return "验证码已过期，请重新发送"
    if isinstance(exc, ApiIdInvalidError):
        return "API ID 或 API Hash 无效，请到 my.telegram.org 核对"
    if isinstance(exc, SessionPasswordNeededError):
        return "该账号已开启两步验证，请输入密码"
    if isinstance(exc, ChannelPrivateError):
        return "该频道是私有的，当前登录账号没有访问权限，请先加入后再采集"
    if isinstance(exc, (UsernameNotOccupiedError, UsernameInvalidError)):
        return "找不到该频道用户名，请检查链接是否正确"
    if isinstance(exc, RPCError):
        message = (getattr(exc, "message", None) or str(exc)).strip()
        return f"Telegram 接口错误：{message or exc.__class__.__name__}"
    return str(exc) or exc.__class__.__name__


def normalize_hashtag(value: str) -> str:
    return value.strip().lstrip("#").casefold()


def extract_hashtags(caption: str | None) -> list[tuple[str, str]]:
    values: dict[str, str] = {}
    for match in HASHTAG_PATTERN.finditer(caption or ""):
        raw = match.group(1)
        normalized = normalize_hashtag(raw)
        if normalized:
            values.setdefault(normalized, raw)
    return [(raw, normalized) for normalized, raw in values.items()]


def media_matches(
    *,
    published_at: datetime,
    media_type: str,
    caption: str | None,
    hashtags: list[tuple[str, str]],
    date_from: datetime | None,
    date_to: datetime | None,
    allowed_media_types: set[str],
    required_hashtags: list[str],
    required_keywords: list[str],
) -> bool:
    if date_from and published_at < date_from:
        return False
    if date_to and published_at > date_to:
        return False
    if media_type not in allowed_media_types:
        return False
    actual_tags = {normalized for _, normalized in hashtags}
    if not all(normalize_hashtag(value) in actual_tags for value in required_hashtags):
        return False
    text = (caption or "").casefold()
    return all(value.casefold() in text for value in required_keywords)


def message_media_type(message: Any) -> str | None:
    if getattr(message, "photo", None):
        return "image"
    if getattr(message, "video", None):
        return "video"
    document = getattr(message, "document", None)
    if document is None:
        return None

    media_file = getattr(message, "file", None)
    mime_type = str(
        getattr(media_file, "mime_type", None)
        or getattr(document, "mime_type", None)
        or ""
    ).lower()
    filename = getattr(media_file, "name", None) or _document_filename(document)
    suffix = Path(str(filename or "")).suffix.lower()
    has_video_attribute = any(
        isinstance(attribute, DocumentAttributeVideo)
        for attribute in getattr(document, "attributes", None) or []
    )
    if mime_type.startswith("image/") or suffix in IMAGE_FILE_EXTENSIONS:
        return "image"
    if mime_type.startswith("video/") or suffix in VIDEO_FILE_EXTENSIONS or has_video_attribute:
        return "video"
    return None


def message_transport_type(message: Any) -> str | None:
    # Telegram 动图同时带 Animated 和 Video 属性，必须先判 gif。
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "gif", None):
        return "animation"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "document", None):
        return "document"
    return None


def _document_filename(document: Any) -> str | None:
    for attribute in getattr(document, "attributes", None) or []:
        filename = getattr(attribute, "file_name", None)
        if filename:
            return str(filename)
    return None


def message_media_suffix(message: Any, media_type: str) -> str:
    document = getattr(message, "document", None)
    media_file = getattr(message, "file", None)
    filename = getattr(media_file, "name", None) or _document_filename(document)
    suffix = Path(str(filename or "")).suffix.lower()
    allowed_extensions = IMAGE_FILE_EXTENSIONS if media_type == "image" else VIDEO_FILE_EXTENSIONS
    if suffix in allowed_extensions:
        return suffix

    mime_type = str(
        getattr(media_file, "mime_type", None)
        or getattr(document, "mime_type", None)
        or ""
    ).lower()
    guessed_suffix = mimetypes.guess_extension(mime_type) if mime_type else None
    if guessed_suffix:
        guessed_suffix = guessed_suffix.lower()
        if guessed_suffix in allowed_extensions:
            return guessed_suffix
    return ".jpg" if media_type == "image" else ".mp4"


def video_metadata(message: Any) -> tuple[float | None, int | None, int | None]:
    video = getattr(message, "video", None) or getattr(message, "document", None)
    for attribute in getattr(video, "attributes", None) or []:
        if isinstance(attribute, DocumentAttributeVideo):
            duration, width, height = attribute.duration, attribute.w, attribute.h
        else:
            duration = getattr(attribute, "duration", None)
            width = getattr(attribute, "w", None)
            height = getattr(attribute, "h", None)
        if duration is None and width is None and height is None:
            continue
        return (
            float(duration) if duration is not None else None,
            int(width) if width is not None else None,
            int(height) if height is not None else None,
        )
    return None, None, None


def message_published_at(message: Any) -> datetime:
    value = message.date
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def grouped_with(buffer: list[Any], message: Any) -> bool:
    if not buffer:
        return False
    grouped_id = getattr(buffer[0], "grouped_id", None)
    return grouped_id is not None and getattr(message, "grouped_id", None) == grouped_id


def scan_iter_kwargs(
    *,
    newest_first: bool,
    date_from: datetime | None,
    date_to: datetime | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"reverse": not newest_first}
    if newest_first and date_to is not None:
        kwargs["offset_date"] = date_to + _MICROSECOND
    elif not newest_first and date_from is not None:
        kwargs["offset_date"] = date_from - _MICROSECOND
    return kwargs


def filter_media_group(
    messages: list[Any],
    *,
    allowed_media_types: set[str],
    required_hashtags: list[str],
    required_keywords: list[str],
    include_comment_roots: bool = False,
) -> list[Any]:
    if not messages:
        return []
    caption_source = min(messages, key=lambda item: int(item.id))
    caption = getattr(caption_source, "message", None) or ""
    tags = extract_hashtags(caption)
    kept = [
        item
        for item in sorted(messages, key=lambda item: int(item.id))
        if include_comment_roots or (
            (media_type := message_media_type(item)) is not None and media_type in allowed_media_types
        )
    ]
    if not kept:
        return []
    sample_type = (
        next(iter(allowed_media_types), "image")
        if include_comment_roots else message_media_type(kept[0]) or "image"
    )
    if not media_matches(
        published_at=message_published_at(caption_source),
        media_type=sample_type,
        caption=caption,
        hashtags=tags,
        date_from=None,
        date_to=None,
        allowed_media_types=allowed_media_types,
        required_hashtags=required_hashtags,
        required_keywords=required_keywords,
    ):
        return []
    return kept


class MediaGroupScanner:
    def __init__(
        self,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        allowed_media_types: set[str],
        required_hashtags: list[str],
        required_keywords: list[str],
        max_messages: int,
        newest_first: bool,
        include_comment_roots: bool = False,
    ) -> None:
        self.date_from = date_from
        self.date_to = date_to
        self.allowed_media_types = allowed_media_types
        self.required_hashtags = required_hashtags
        self.required_keywords = required_keywords
        self.max_messages = max_messages
        self.newest_first = newest_first
        self.include_comment_roots = include_comment_roots
        self.buffer: list[Any] = []
        self.matched = 0
        self.done = False

    def _past_end(self, published_at: datetime) -> bool:
        if self.newest_first:
            return bool(self.date_from and published_at < self.date_from)
        return bool(self.date_to and published_at > self.date_to)

    def _before_window(self, published_at: datetime) -> bool:
        if self.newest_first:
            return bool(self.date_to and published_at > self.date_to)
        return bool(self.date_from and published_at < self.date_from)

    def push(self, message: Any) -> list[list[Any]]:
        if self.done:
            return []
        published_at = message_published_at(message)
        completed: list[list[Any]] = []
        if self._past_end(published_at):
            if grouped_with(self.buffer, message):
                self.buffer.append(message)
                return []
            completed.extend(self._flush())
            self.done = True
            return completed
        if self._before_window(published_at):
            return []
        if self.buffer and not grouped_with(self.buffer, message):
            completed.extend(self._flush())
            if self.done:
                return completed
        if grouped_with(self.buffer, message):
            self.buffer.append(message)
            return completed
        if message_media_type(message) is None and not self.include_comment_roots:
            return completed
        self.buffer = [message]
        return completed

    def finish(self) -> list[list[Any]]:
        return self._flush()

    def _flush(self) -> list[list[Any]]:
        if not self.buffer:
            return []
        kept = filter_media_group(
            self.buffer,
            allowed_media_types=self.allowed_media_types,
            required_hashtags=self.required_hashtags,
            required_keywords=self.required_keywords,
            include_comment_roots=self.include_comment_roots,
        )
        self.buffer = []
        if not kept:
            return []
        self.matched += 1
        if self.matched >= self.max_messages:
            self.done = True
        return [kept]


def select_matching_media_groups(
    messages: Iterable[Any],
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    allowed_media_types: set[str],
    required_hashtags: list[str],
    required_keywords: list[str],
    max_messages: int,
    newest_first: bool,
    safety_limit: int | None = None,
) -> list[list[Any]]:
    scanner = MediaGroupScanner(
        date_from=date_from,
        date_to=date_to,
        allowed_media_types=allowed_media_types,
        required_hashtags=required_hashtags,
        required_keywords=required_keywords,
        max_messages=max_messages,
        newest_first=newest_first,
    )
    cap = safety_limit if safety_limit is not None else max(max_messages * 50, 1000)
    groups: list[list[Any]] = []
    for index, message in enumerate(messages, start=1):
        groups.extend(scanner.push(message))
        if scanner.done or index >= cap:
            break
    groups.extend(scanner.finish())
    return groups


class TelegramRunAborted(Exception):
    """用户已请求停止本次 Telegram 采集。"""


class TelegramService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _cipher(self) -> Fernet:
        raw = self.settings.telegram_session_encryption_key.strip()
        if not raw:
            raise ValueError("尚未配置 TELEGRAM_SESSION_ENCRYPTION_KEY")
        try:
            return Fernet(raw.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ValueError("TELEGRAM_SESSION_ENCRYPTION_KEY 必须是有效的 Fernet 密钥") from exc

    def encrypt(self, value: str) -> str:
        return self._cipher().encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._cipher().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError) as exc:
            raise ValueError("Telegram 账号凭证无法解密") from exc

    @staticmethod
    def mask_phone(phone: str) -> str:
        compact = phone.strip()
        if len(compact) <= 4:
            return "*" * len(compact)
        return f"{compact[:3]}{'*' * max(4, len(compact) - 6)}{compact[-3:]}"

    @staticmethod
    def _run(coro: Any) -> Any:
        return asyncio.run(coro)

    def _encode_pending(
        self,
        *,
        phone_number: str,
        phone_code_hash: str,
        session: str,
        code_delivery: str,
    ) -> str:
        payload = {
            "phone_number": phone_number,
            "phone_code_hash": phone_code_hash,
            "session": session,
            "code_delivery": code_delivery,
        }
        return self.encrypt(json.dumps(payload, ensure_ascii=False))

    def _decode_pending(self, encrypted: str | None) -> dict[str, str]:
        if not encrypted:
            raise ValueError("登录事务已失效，请重新发送验证码")
        raw = self.decrypt(encrypted)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            phone, separator, code_hash = raw.partition("\n")
            if not separator or not phone or not code_hash:
                raise ValueError("登录事务已失效，请重新发送验证码")
            return {
                "phone_number": phone,
                "phone_code_hash": code_hash,
                "session": "",
                "code_delivery": "unknown",
            }
        phone_number = str(payload.get("phone_number") or "").strip()
        phone_code_hash = str(payload.get("phone_code_hash") or "").strip()
        session = str(payload.get("session") or "")
        code_delivery = str(payload.get("code_delivery") or "unknown")
        if not phone_number or not phone_code_hash:
            raise ValueError("登录事务已失效，请重新发送验证码")
        return {
            "phone_number": phone_number,
            "phone_code_hash": phone_code_hash,
            "session": session,
            "code_delivery": code_delivery,
        }

    def read_pending_code_delivery(self, account: TelegramAccount | None) -> str | None:
        if account is None or not account.pending_login_state_encrypted:
            return None
        try:
            return self._decode_pending(account.pending_login_state_encrypted).get("code_delivery") or None
        except ValueError:
            return None

    async def _start_login_async(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        session_string: str = "",
    ) -> TelegramLoginStart:
        session = StringSession(session_string or "")
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            delivery = code_delivery_from_type(getattr(sent, "type", None))
            LOGGER.info(
                "Telegram 验证码已请求 phone=%s delivery=%s type=%s",
                self.mask_phone(phone),
                delivery,
                type(getattr(sent, "type", None)).__name__,
            )
            return TelegramLoginStart(
                phone_code_hash=sent.phone_code_hash,
                phone_number=phone,
                session=session.save(),
                code_delivery=delivery,
            )
        finally:
            await client.disconnect()

    def start_login(
        self,
        account: TelegramAccount | None,
        workspace_id: int,
        api_id: int,
        api_hash: str,
        phone: str,
    ) -> TelegramAccount:
        phone_number = normalize_phone_number(phone)
        LOGGER.info("Telegram 登录手机号已规范化 raw=%s normalized=%s", self.mask_phone(phone), self.mask_phone(phone_number))
        try:
            result = self._run(self._start_login_async(api_id, api_hash.strip(), phone_number))
        except Exception as exc:  # noqa: BLE001 - translate all telethon failures
            raise ValueError(translate_telegram_error(exc)) from exc
        pending = self._encode_pending(
            phone_number=result.phone_number,
            phone_code_hash=result.phone_code_hash,
            session=result.session,
            code_delivery=result.code_delivery,
        )
        if account is None:
            account = TelegramAccount(
                workspace_id=workspace_id,
                api_id=api_id,
                api_hash_encrypted=self.encrypt(api_hash.strip()),
            )
        else:
            account.api_id = api_id
            account.api_hash_encrypted = self.encrypt(api_hash.strip())
        account.pending_login_state_encrypted = pending
        account.phone_masked = self.mask_phone(phone_number)
        account.session_encrypted = None
        account.telegram_user_id = None
        account.username = None
        account.status = "verification_pending"
        return account

    def resend_login_code(self, account: TelegramAccount) -> TelegramAccount:
        if not account.api_hash_encrypted:
            raise ValueError("尚未保存 API 凭证，请重新填写后发送验证码")
        pending = self._decode_pending(account.pending_login_state_encrypted)
        phone_number = normalize_phone_number(pending["phone_number"])
        api_hash = self.decrypt(account.api_hash_encrypted)
        try:
            result = self._run(
                self._start_login_async(
                    account.api_id,
                    api_hash,
                    phone_number,
                    session_string=pending.get("session") or "",
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc
        account.pending_login_state_encrypted = self._encode_pending(
            phone_number=result.phone_number,
            phone_code_hash=result.phone_code_hash,
            session=result.session,
            code_delivery=result.code_delivery,
        )
        account.phone_masked = self.mask_phone(result.phone_number)
        account.session_encrypted = None
        account.status = "verification_pending"
        return account

    def clear_pending_login(self, account: TelegramAccount) -> None:
        account.pending_login_state_encrypted = None
        if account.session_encrypted:
            account.status = "active"
        else:
            account.status = "logged_out" if account.api_id else "unconfigured"

    async def _verify_login_async(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        code_hash: str,
        code: str,
        password: str | None,
        session_string: str,
    ) -> tuple[str, int, str | None]:
        session = StringSession(session_string or "")
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        try:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            except SessionPasswordNeededError:
                if not password:
                    raise ValueError("该账号已开启两步验证，请输入密码")
                await client.sign_in(password=password)
            user = await client.get_me()
            if user is None:
                raise ValueError("Telegram 登录未返回账号信息")
            return session.save(), int(user.id), getattr(user, "username", None)
        finally:
            await client.disconnect()

    def verify_login(self, account: TelegramAccount, code: str, password: str | None) -> None:
        pending = self._decode_pending(account.pending_login_state_encrypted)
        try:
            session, user_id, username = self._run(
                self._verify_login_async(
                    account.api_id,
                    self.decrypt(account.api_hash_encrypted),
                    pending["phone_number"],
                    pending["phone_code_hash"],
                    code,
                    password,
                    pending.get("session") or "",
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc
        account.session_encrypted = self.encrypt(session)
        account.pending_login_state_encrypted = None
        account.telegram_user_id = user_id
        account.username = username
        account.status = "active"
        account.last_login_at = shanghai_now()

    async def _test_async(self, account: TelegramAccount) -> tuple[int, str | None]:
        client = TelegramClient(
            StringSession(self.decrypt(account.session_encrypted or "")),
            account.api_id,
            self.decrypt(account.api_hash_encrypted),
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise ValueError("Telegram 登录会话已失效")
            user = await client.get_me()
            if user is None:
                raise ValueError("无法读取 Telegram 账号")
            return int(user.id), getattr(user, "username", None)
        finally:
            await client.disconnect()

    def test_account(self, account: TelegramAccount) -> None:
        try:
            user_id, username = self._run(self._test_async(account))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc
        account.telegram_user_id = user_id
        account.username = username
        account.status = "active"
        account.last_login_at = shanghai_now()

    def logout(self, account: TelegramAccount) -> None:
        account.session_encrypted = None
        account.pending_login_state_encrypted = None
        account.telegram_user_id = None
        account.username = None
        account.status = "logged_out"

    async def _open_client(self, account: TelegramAccount) -> TelegramClient:
        client = TelegramClient(
            StringSession(self.decrypt(account.session_encrypted or "")),
            account.api_id,
            self.decrypt(account.api_hash_encrypted),
        )
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise ValueError("Telegram 登录会话已失效，请重新登录")
        return client

    def _store_client_session(self, account: TelegramAccount, client: TelegramClient) -> None:
        session_obj = getattr(client, "session", None)
        save = getattr(session_obj, "save", None)
        if not callable(save):
            return
        session = save()
        if session:
            account.session_encrypted = self.encrypt(session)

    async def _close_client(self, account: TelegramAccount, client: TelegramClient) -> None:
        try:
            self._store_client_session(account, client)
        finally:
            await client.disconnect()

    async def _list_dialogs_async(self, account: TelegramAccount) -> list[dict[str, object]]:
        client = await self._open_client(account)
        try:
            result: list[dict[str, object]] = []
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if not isinstance(entity, (types.User, types.Chat, types.Channel)):
                    continue
                if isinstance(entity, types.User):
                    entity_type = "bot" if bool(getattr(entity, "bot", False)) else "user"
                elif isinstance(entity, types.Channel):
                    entity_type = "group" if bool(getattr(entity, "megagroup", False)) else "channel"
                else:
                    entity_type = "group"
                if entity_type == "user":
                    continue
                peer_id = str(await client.get_peer_id(entity))
                result.append({
                    "peer_id": peer_id,
                    "title": dialog.name or getattr(entity, "title", None) or getattr(entity, "username", None) or peer_id,
                    "username": getattr(entity, "username", None),
                    "entity_type": entity_type,
                    "is_bot": bool(getattr(entity, "bot", False)),
                    "is_forum": bool(getattr(entity, "forum", False)),
                    "unread_count": int(getattr(dialog, "unread_count", 0) or 0),
                })
            return result
        finally:
            await self._close_client(account, client)

    def list_dialogs(self, account: TelegramAccount) -> list[dict[str, object]]:
        try:
            return self._run(self._list_dialogs_async(account))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc

    async def _list_topics_async(self, account: TelegramAccount, peer_id: str) -> list[dict[str, object]]:
        client = await self._open_client(account)
        try:
            entity = await self._resolve_target(client, channel_ref=peer_id, peer_id=peer_id)
            return await self._forum_topics_for_entity(client, entity)
        finally:
            await self._close_client(account, client)

    def list_topics(self, account: TelegramAccount, peer_id: str) -> list[dict[str, object]]:
        try:
            return self._run(self._list_topics_async(account, peer_id))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc

    async def _scan_forum_topics_async(self, account: TelegramAccount, channel_ref: str) -> dict[str, object]:
        client = await self._open_client(account)
        try:
            entity = await self._resolve_target(client, channel_ref=channel_ref)
            peer_id = str(await client.get_peer_id(entity))
            is_forum = bool(getattr(entity, "forum", False))
            return {
                **self._describe_telegram_entity(entity, peer_id),
                "is_forum": is_forum,
                "topics": await self._forum_topics_for_entity(client, entity) if is_forum else [],
            }
        finally:
            await self._close_client(account, client)

    def scan_forum_topics(self, account: TelegramAccount, channel_ref: str) -> dict[str, object]:
        normalized = channel_ref.strip()
        if not normalized:
            raise ValueError("请输入频道链接")
        try:
            return self._run(self._scan_forum_topics_async(account, normalized))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc

    async def _forum_topics_for_entity(self, client: TelegramClient, entity: Any) -> list[dict[str, object]]:
        if not bool(getattr(entity, "forum", False)):
            return []
        topics = await client(
            functions.messages.GetForumTopicsRequest(
                peer=entity,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=100,
            )
        )
        return self._serialize_forum_topics(topics)

    @staticmethod
    def _describe_telegram_entity(entity: Any, peer_id: str) -> dict[str, object]:
        if isinstance(entity, types.User):
            entity_type = "bot" if bool(getattr(entity, "bot", False)) else "user"
        elif isinstance(entity, types.Channel):
            entity_type = "group" if bool(getattr(entity, "megagroup", False)) else "channel"
        else:
            entity_type = "group"
        title = (
            getattr(entity, "title", None)
            or getattr(entity, "username", None)
            or getattr(entity, "first_name", None)
            or peer_id
        )
        return {
            "peer_id": peer_id,
            "title": str(title),
            "username": getattr(entity, "username", None),
            "entity_type": entity_type,
        }

    @staticmethod
    def _serialize_forum_topics(topics: Any) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for topic in getattr(topics, "topics", []):
            result.append({
                "topic_id": int(getattr(topic, "id", 0)),
                "title": str(getattr(topic, "title", "") or "未命名话题"),
                "closed": bool(getattr(topic, "closed", False)),
                "pinned": bool(getattr(topic, "pinned", False)),
                "date": as_shanghai_naive(getattr(topic, "date", None)) if getattr(topic, "date", None) else None,
            })
        return result

    def read_channel_media(
        self,
        account: TelegramAccount,
        channel_ref: str,
        parameters: dict[str, object],
        target_dir: Path,
        on_records: Callable[[list[dict[str, object]]], None] | None = None,
        abort_event: threading.Event | None = None,
    ) -> list[dict[str, object]]:
        try:
            return self._run(
                self._read_channel_media_async(
                    account, channel_ref, parameters, target_dir, on_records, abort_event,
                )
            )
        except TelegramRunAborted:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ValueError(translate_telegram_error(exc)) from exc

    async def _read_channel_media_async(
        self,
        account: TelegramAccount,
        channel_ref: str,
        parameters: dict[str, object],
        target_dir: Path,
        on_records: Callable[[list[dict[str, object]]], None] | None = None,
        abort_event: threading.Event | None = None,
    ) -> list[dict[str, object]]:
        client = TelegramClient(
            StringSession(self.decrypt(account.session_encrypted or "")),
            account.api_id,
            self.decrypt(account.api_hash_encrypted),
            request_retries=_COLLECTION_REQUEST_RETRIES,
            receive_updates=False,
            timeout=_COLLECTION_REQUEST_TIMEOUT,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise ValueError("Telegram 登录会话已失效，请重新登录")
            channel = await self._resolve_target(
                client,
                channel_ref=channel_ref,
                peer_id=parameters.get("peer_id"),
                username=parameters.get("username"),
            )
            comments_only = bool(parameters.get("comments_only"))
            if comments_only and (
                parameters.get("topic_id") or bool(getattr(channel, "megagroup", False))
                or isinstance(channel, (types.User, types.Chat))
            ):
                raise ValueError("仅采集评论区媒体只支持频道，不支持机器人、群组或论坛话题")
            collect_comments = bool(parameters.get("collect_comments")) or comments_only
            date_from = self._parse_datetime(parameters.get("date_from"))
            date_to = self._parse_datetime(parameters.get("date_to"))
            media_types = {str(item) for item in parameters.get("media_types", ["image", "video"])}
            hashtags = [str(item) for item in parameters.get("hashtags", [])]
            keywords = [str(item) for item in parameters.get("caption_keywords", [])]
            max_messages = int(parameters.get("max_messages") or 1000)
            newest_first = str(parameters.get("scan_order") or "newest") != "oldest"
            safety_limit = max(max_messages * 50, 1000)
            target_dir.mkdir(parents=True, exist_ok=True)
            scanner = MediaGroupScanner(
                date_from=date_from,
                date_to=date_to,
                allowed_media_types=media_types,
                required_hashtags=hashtags,
                required_keywords=keywords,
                max_messages=max_messages,
                newest_first=newest_first,
                include_comment_roots=comments_only,
            )
            LOGGER.info(
                "Telegram 采集开始 channel=%s max_messages=%s order=%s date_from=%s date_to=%s",
                channel_ref,
                max_messages,
                "newest" if newest_first else "oldest",
                date_from,
                date_to,
            )
            records: list[dict[str, object]] = []
            seen = 0

            async def emit(group: list[Any]) -> None:
                self._raise_if_aborted(abort_event)
                if not comments_only:
                    batch = await self._download_media_group(client, channel, group, target_dir, abort_event)
                    await emit_records(batch)
                if collect_comments and not parameters.get("topic_id"):
                    await self._emit_comment_media(
                        client, channel, group[0], target_dir, media_types, emit_records, abort_event,
                        inherit_root_caption=comments_only,
                    )

            topic_titles: dict[int, str | None] = {}

            async def emit_records(batch: list[dict[str, object]]) -> None:
                if not batch:
                    return
                for record in batch:
                    topic = record.get("topic_id")
                    if topic and not record.get("is_comment"):
                        topic = int(topic)
                        if topic not in topic_titles:
                            try:
                                topics = await client(functions.messages.GetForumTopicsByIDRequest(peer=channel, topics=[topic]))
                                topic_titles[topic] = next((str(t.title) for t in topics.topics if t.id == topic), None)
                            except Exception:
                                topic_titles[topic] = None
                        record["topic_title"] = topic_titles[topic]
                if on_records is not None:
                    on_records(batch)
                records.extend(batch)

            iterator_kwargs = scan_iter_kwargs(newest_first=newest_first, date_from=date_from, date_to=date_to)
            topic_id = parameters.get("topic_id")
            if topic_id:
                iterator_kwargs["reply_to"] = int(topic_id)
            async for message in client.iter_messages(channel, **iterator_kwargs):
                self._raise_if_aborted(abort_event)
                seen += 1
                completed_groups = scanner.push(message)
                for group in completed_groups:
                    await emit(group)
                if scanner.done or seen >= safety_limit:
                    break
            self._raise_if_aborted(abort_event)
            for group in scanner.finish():
                await emit(group)
            LOGGER.info("Telegram 采集结束 matched_messages=%s media=%s scanned_api=%s", scanner.matched, len(records), seen)
            return records
        except FloodWaitError as exc:
            if exc.seconds > self.settings.telegram_flood_wait_max_seconds:
                raise ValueError(f"Telegram 限流等待时间过长：{exc.seconds} 秒") from exc
            await asyncio.sleep(exc.seconds)
            raise ValueError("Telegram 限流，请重新运行采集任务") from exc
        finally:
            await self._close_client(account, client)

    async def _emit_comment_media(
        self,
        client: TelegramClient,
        channel: Any,
        root_message: Any,
        target_dir: Path,
        media_types: set[str],
        emit: Callable[[list[dict[str, object]]], Any],
        abort_event: threading.Event | None = None,
        *,
        inherit_root_caption: bool = False,
    ) -> None:
        self._raise_if_aborted(abort_event)
        try:
            comments = [message async for message in client.iter_messages(channel, reply_to=int(root_message.id), limit=500)]
        except TelegramRunAborted:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Telegram 评论读取失败 channel=%s message_id=%s: %s", getattr(channel, "id", None), root_message.id, exc)
            return
        for comment in comments:
            self._raise_if_aborted(abort_event)
            if message_media_type(comment) not in media_types:
                continue
            comment.grouped_id = None
            batch = await self._download_media_group(client, channel, [comment], target_dir, abort_event)
            for record in batch:
                if inherit_root_caption:
                    captions = dict.fromkeys(filter(None, [
                        getattr(root_message, "message", None), record.get("caption"),
                    ]))
                    record["caption"] = "\n\n".join(captions) or None
                    record["hashtags"] = extract_hashtags(record["caption"])
                record["is_comment"] = True
                record["root_channel_message_id"] = int(root_message.id)
                record["root_channel_id"] = str(channel.id)
                record["root_channel_title"] = getattr(channel, "title", None)
                record["root_channel_username"] = getattr(channel, "username", None)
                root_path = getattr(channel, "username", None) or f"c/{channel.id}"
                record["source_url"] = f"https://t.me/{root_path}/{root_message.id}?comment={comment.id}"
                record["topic_id"] = None
                record["topic_title"] = None
                record["reply_to_message_id"] = getattr(getattr(comment, "reply_to", None), "reply_to_msg_id", None)
                record["external_key"] = f"{record['channel_id']}:{comment.id}:1"
            if batch:
                await emit(batch)

    @staticmethod
    def _raise_if_aborted(abort_event: threading.Event | None) -> None:
        if abort_event is not None and abort_event.is_set():
            raise TelegramRunAborted()

    async def _sleep_or_abort(self, seconds: float, abort_event: threading.Event | None) -> None:
        self._raise_if_aborted(abort_event)
        remaining = max(0.0, float(seconds))
        if remaining == 0:
            return
        if abort_event is None:
            await asyncio.sleep(remaining)
            return
        while remaining > 0:
            self._raise_if_aborted(abort_event)
            step = min(_ABORT_POLL_SECONDS, remaining)
            await asyncio.sleep(step)
            remaining -= step
        self._raise_if_aborted(abort_event)

    async def _watch_abort(self, abort_event: threading.Event) -> None:
        while not abort_event.is_set():
            await asyncio.sleep(_ABORT_POLL_SECONDS)

    async def _download_once(
        self,
        client: TelegramClient,
        message: Any,
        path: Path,
        timeout: float,
        abort_event: threading.Event | None,
    ) -> object:
        download_task = asyncio.create_task(client.download_media(message, file=str(path)))
        watcher = asyncio.create_task(self._watch_abort(abort_event)) if abort_event is not None else None
        try:
            waiting = {download_task}
            if watcher is not None:
                waiting.add(watcher)
            done, _pending = await asyncio.wait(
                waiting,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            self._raise_if_aborted(abort_event)
            if download_task not in done:
                raise TimeoutError()
            return download_task.result()
        finally:
            if watcher is not None and not watcher.done():
                watcher.cancel()
            if not download_task.done():
                download_task.cancel()
            pending = [task for task in (download_task, watcher) if task is not None]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _reconnect_download_client(self, client: TelegramClient) -> None:
        await client.disconnect()
        await client.connect()
        if not await client.is_user_authorized():
            raise ValueError("Telegram 登录会话已失效，请重新登录")

    @staticmethod
    def _is_file_download_stall(exc: BaseException) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        text = str(exc)
        return "Request was unsuccessful" in text or "GetFileRequest" in text

    @staticmethod
    def _discard_partial_download(path: Path) -> None:
        path.unlink(missing_ok=True)

    async def _download_message_media(
        self,
        client: TelegramClient,
        message: Any,
        path: Path,
        abort_event: threading.Event | None = None,
    ) -> Path | None:
        timeout = max(1, int(self.settings.telegram_download_timeout_seconds))
        attempts = 3
        message_id = getattr(message, "id", None)
        for attempt in range(1, attempts + 1):
            self._raise_if_aborted(abort_event)
            started = time.monotonic()
            try:
                downloaded = await self._download_once(client, message, path, timeout, abort_event)
                if not downloaded:
                    self._discard_partial_download(path)
                    return None
                media_path = Path(downloaded)
                elapsed = time.monotonic() - started
                size = media_path.stat().st_size if media_path.is_file() else 0
                LOGGER.info(
                    "Telegram 媒体已下载 message_id=%s bytes=%s seconds=%.1f attempt=%s",
                    message_id,
                    size,
                    elapsed,
                    attempt,
                )
                return media_path
            except TelegramRunAborted:
                self._discard_partial_download(path)
                raise
            except FloodWaitError as exc:
                self._discard_partial_download(path)
                if exc.seconds > self.settings.telegram_flood_wait_max_seconds:
                    raise
                LOGGER.warning(
                    "Telegram 限流 message_id=%s，等待 %s 秒后重试",
                    message_id,
                    exc.seconds,
                )
                await self._sleep_or_abort(exc.seconds, abort_event)
                continue
            except ChatForwardsRestrictedError:
                self._discard_partial_download(path)
                LOGGER.warning("Telegram 拒绝下载受保护媒体 message_id=%s", message_id)
                return None
            except Exception as exc:  # noqa: BLE001 - keep the run going after a single media failure
                stalled = self._is_file_download_stall(exc)
                if stalled:
                    LOGGER.warning(
                        "Telegram 文件下载超时（不是限流） message_id=%s attempt=%s: %s",
                        message_id,
                        attempt,
                        exc,
                    )
                else:
                    LOGGER.warning(
                        "Telegram 媒体下载失败 message_id=%s attempt=%s: %s",
                        message_id,
                        attempt,
                        exc,
                    )
                self._discard_partial_download(path)
                if attempt >= attempts:
                    break
                if stalled:
                    try:
                        await self._reconnect_download_client(client)
                    except TelegramRunAborted:
                        raise
                    except ValueError:
                        raise
                    except Exception as reconnect_exc:  # noqa: BLE001
                        LOGGER.warning(
                            "Telegram 文件连接重连失败 message_id=%s: %s",
                            message_id,
                            reconnect_exc,
                        )
                    await self._sleep_or_abort(_FILE_STALL_BACKOFF_SECONDS[attempt - 1], abort_event)
                else:
                    await self._sleep_or_abort(min(2 ** attempt, 8), abort_event)
        self._discard_partial_download(path)
        return None

    async def _download_media_group(
        self,
        client: TelegramClient,
        channel: Any,
        messages: list[Any],
        target_dir: Path,
        abort_event: threading.Event | None = None,
    ) -> list[dict[str, object]]:
        caption_source = min(messages, key=lambda item: int(item.id))
        caption = getattr(caption_source, "message", None) or ""
        tags = extract_hashtags(caption)
        protected_channel = bool(getattr(channel, "noforwards", False))
        records: list[dict[str, object]] = []
        for message in messages:
            self._raise_if_aborted(abort_event)
            media_type = message_media_type(message)
            if media_type is None:
                continue
            protected = protected_channel or bool(getattr(message, "noforwards", False))
            suffix = message_media_suffix(message, media_type)
            path = target_dir / f"{getattr(channel, 'id', 'channel')}-{message.id}{suffix}"
            media_path = await self._download_message_media(client, message, path, abort_event)
            if media_path is None or not media_path.is_file():
                if protected:
                    records.append(self._record(message, channel, media_type, caption, tags, None, True))
                continue
            if media_path.stat().st_size > self.settings.telegram_max_media_bytes:
                LOGGER.warning("Telegram 媒体超过大小上限，已跳过 message_id=%s", getattr(message, "id", None))
                media_path.unlink(missing_ok=True)
                continue
            records.append(self._record(message, channel, media_type, caption, tags, media_path, protected))
        return records

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
        return parsed.astimezone(timezone.utc)

    async def _resolve_target(
        self,
        client: TelegramClient,
        *,
        channel_ref: str,
        peer_id: object = None,
        username: object = None,
    ) -> Any:
        last_exc: BaseException | None = None
        for candidate in self._resolve_candidates(channel_ref, peer_id, username):
            try:
                return await self._resolve_channel(client, candidate)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if self._should_raise_resolve_error(exc):
                    raise
        numeric_ref = str(peer_id or "").strip() or (channel_ref.strip() if re.fullmatch(r"-?\d+", channel_ref.strip()) else "")
        if numeric_ref:
            found = await self._find_dialog_entity(client, numeric_ref)
            if found is not None:
                return found
        if last_exc is not None:
            raise ValueError(translate_telegram_error(last_exc)) from last_exc
        raise ValueError("无法解析 Telegram 频道，请检查链接或会话")

    @staticmethod
    def _resolve_candidates(channel_ref: str, peer_id: object = None, username: object = None) -> list[str]:
        candidates: list[str] = []

        def add(value: str | None) -> None:
            text = (value or "").strip()
            if text and text not in candidates:
                candidates.append(text)

        name = str(username or "").strip().lstrip("@")
        if name:
            add(f"@{name}")
            add(name)
        ref = (channel_ref or "").strip()
        add(TelegramService._public_ref_lookup(ref))
        add(ref)
        add(str(peer_id or "").strip() or None)
        return candidates

    @staticmethod
    def _public_ref_lookup(channel_ref: str) -> str | None:
        normalized = channel_ref.strip()
        if not normalized:
            return None
        if normalized.startswith("@"):
            return normalized
        has_host = "://" in normalized or normalized.startswith("t.me/") or normalized.startswith("telegram.me/")
        if not has_host:
            return None
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        parts = [item for item in parsed.path.strip("/").split("/") if item]
        if not parts:
            return None
        if parts[0].startswith("+") or parts[0] == "joinchat":
            return normalized
        if parts[0] == "c" and len(parts) >= 2 and parts[1].isdigit():
            return f"-100{parts[1]}"
        username = parts[0].removeprefix("@")
        if username and not re.fullmatch(r"-?\d+", username):
            return f"@{username}"
        return None

    @staticmethod
    def _peer_id_aliases(value: str) -> set[str]:
        text = value.strip()
        aliases = {text}
        if re.fullmatch(r"-?\d+", text):
            number = int(text)
            aliases.add(str(number))
            as_text = str(number)
            if number < 0 and as_text.startswith("-100"):
                aliases.add(as_text[4:])
            elif number > 0:
                aliases.add(f"-100{number}")
        return aliases

    @staticmethod
    def _is_missing_input_entity(exc: BaseException) -> bool:
        return "Could not find the input entity" in str(exc)

    @staticmethod
    def _should_raise_resolve_error(exc: BaseException) -> bool:
        if isinstance(exc, FloodWaitError):
            return True
        if isinstance(exc, ValueError) and "请先使用 Telegram 客户端加入" in str(exc):
            return True
        if TelegramService._is_missing_input_entity(exc):
            return False
        return not isinstance(exc, (UsernameInvalidError, UsernameNotOccupiedError, ChannelPrivateError, ValueError))

    @staticmethod
    async def _find_dialog_entity(client: TelegramClient, peer_id: str) -> Any | None:
        aliases = TelegramService._peer_id_aliases(peer_id)
        async for dialog in client.iter_dialogs():
            entity = getattr(dialog, "entity", None)
            if entity is None:
                continue
            entity_id = str(getattr(entity, "id", "") or "")
            try:
                current = str(await client.get_peer_id(entity))
            except Exception:  # noqa: BLE001
                current = entity_id
            if current in aliases or entity_id in aliases:
                return entity
        return None

    @staticmethod
    async def _resolve_channel(client: TelegramClient, channel_ref: str) -> Any:
        normalized = channel_ref.strip()
        lookup = TelegramService._public_ref_lookup(normalized)
        if lookup and lookup != normalized and not lookup.startswith("-"):
            normalized = lookup
        elif lookup and lookup.startswith("-100") and re.fullmatch(r"-100\d+", lookup):
            normalized = lookup
        parsed = urlparse(normalized)
        path = parsed.path.strip("/") if parsed.scheme else normalized.removeprefix("t.me/").strip("/")
        invite_hash: str | None = None
        if path.startswith("+"):
            invite_hash = path[1:]
        elif path.startswith("joinchat/"):
            invite_hash = path.removeprefix("joinchat/")
        if invite_hash:
            invite = await client(CheckChatInviteRequest(invite_hash))
            if not isinstance(invite, ChatInviteAlready):
                raise ValueError("请先使用 Telegram 客户端加入该私人频道")
            return invite.chat
        if re.fullmatch(r"-?\d+", normalized):
            return await client.get_entity(int(normalized))
        return await client.get_entity(normalized)

    @staticmethod
    def _record(
        message: Any,
        channel: Any,
        media_type: str,
        caption: str,
        tags: list[tuple[str, str]],
        path: Path | None,
        protected: bool,
    ) -> dict[str, object]:
        username = getattr(channel, "username", None)
        channel_id = str(getattr(channel, "id", ""))
        channel_title = getattr(channel, "title", None)
        actual_peer = getattr(getattr(message, "peer_id", None), "channel_id", None)
        # 评论消息实际属于讨论组，但来源键必须继续用频道 id，保持增量采集兼容旧数据。
        discussion_peer_id = (
            str(actual_peer) if actual_peer is not None and str(actual_peer) != channel_id else None
        )
        reply = getattr(message, "reply_to", None)
        topic_id = None
        if bool(getattr(reply, "forum_topic", False)):
            topic_id = getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None)
        elif bool(getattr(channel, "forum", False)):
            topic_id = 1
        duration, width, height = video_metadata(message) if media_type == "video" else (None, None, None)
        document = getattr(message, "document", None)
        media_file = getattr(message, "file", None)
        content_type = (
            getattr(media_file, "mime_type", None)
            or getattr(document, "mime_type", None)
        )
        return {
            "external_key": f"{channel_id}:{message.id}:{1 if getattr(message, 'is_comment', False) else 0}",
            "source_url": f"https://t.me/{username}/{message.id}" if username else f"https://t.me/c/{channel_id}/{message.id}",
            "filename": path.name if path else f"telegram-{channel_id}-{message.id}",
            "path": path,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "channel_username": username,
            "message_id": message.id,
            "grouped_id": str(message.grouped_id) if message.grouped_id else None,
            "media_type": media_type,
            "transport_type": message_transport_type(message),
            "original_filename": getattr(media_file, "name", None) or _document_filename(document),
            "content_type": content_type,
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "published_at": as_shanghai_naive(message.date),
            "edited_at": as_shanghai_naive(message.edit_date) if message.edit_date else None,
            "caption": caption or None,
            "hashtags": tags,
            "protected_content": protected,
            "peer_id": discussion_peer_id or channel_id,
            "discussion_peer_id": discussion_peer_id,
            "entity_type": "group" if bool(getattr(channel, "megagroup", False)) or discussion_peer_id else "channel",
            "sender_id": getattr(getattr(message, "sender", None), "id", None),
            "sender_username": getattr(getattr(message, "sender", None), "username", None),
            "sender_is_bot": bool(getattr(getattr(message, "sender", None), "bot", False)),
            "reply_to_message_id": getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
            "topic_id": topic_id,
            "is_comment": bool(getattr(message, "is_comment", False)),
            "root_channel_message_id": None,
        }
