from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import ChatInviteAlready

from app.core.config import Settings
from app.core.timezones import as_shanghai_naive, shanghai_now
from app.models import TelegramAccount


HASHTAG_PATTERN = re.compile(r"(?<!\w)#([\w\u4e00-\u9fff-]+)", re.UNICODE)


@dataclass(frozen=True)
class TelegramLoginStart:
    phone_code_hash: str
    phone_number: str


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

    async def _start_login_async(self, api_id: int, api_hash: str, phone: str) -> TelegramLoginStart:
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            return TelegramLoginStart(phone_code_hash=sent.phone_code_hash, phone_number=phone)
        finally:
            await client.disconnect()

    def start_login(self, account: TelegramAccount | None, workspace_id: int, api_id: int, api_hash: str, phone: str) -> TelegramAccount:
        result = self._run(self._start_login_async(api_id, api_hash, phone))
        pending = f"{result.phone_number}\n{result.phone_code_hash}"
        if account is None:
            account = TelegramAccount(
                workspace_id=workspace_id,
                api_id=api_id,
                api_hash_encrypted=self.encrypt(api_hash),
            )
        else:
            account.api_id = api_id
            account.api_hash_encrypted = self.encrypt(api_hash)
        account.pending_login_state_encrypted = self.encrypt(pending)
        account.phone_masked = self.mask_phone(phone)
        account.session_encrypted = None
        account.status = "verification_pending"
        return account

    async def _verify_login_async(self, api_id: int, api_hash: str, phone: str, code_hash: str, code: str, password: str | None) -> tuple[str, int, str | None]:
        session = StringSession()
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
        pending = self.decrypt(account.pending_login_state_encrypted or "")
        phone, separator, code_hash = pending.partition("\n")
        if not separator or not phone or not code_hash:
            raise ValueError("登录事务已失效，请重新发送验证码")
        session, user_id, username = self._run(self._verify_login_async(
            account.api_id, self.decrypt(account.api_hash_encrypted), phone, code_hash, code, password
        ))
        account.session_encrypted = self.encrypt(session)
        account.pending_login_state_encrypted = None
        account.telegram_user_id = user_id
        account.username = username
        account.status = "active"
        account.last_login_at = shanghai_now()

    async def _test_async(self, account: TelegramAccount) -> tuple[int, str | None]:
        client = TelegramClient(StringSession(self.decrypt(account.session_encrypted or "")), account.api_id, self.decrypt(account.api_hash_encrypted))
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
        user_id, username = self._run(self._test_async(account))
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

    def read_channel_media(
        self,
        account: TelegramAccount,
        channel_ref: str,
        parameters: dict[str, object],
        target_dir: Path,
    ) -> list[dict[str, object]]:
        return self._run(self._read_channel_media_async(account, channel_ref, parameters, target_dir))

    async def _read_channel_media_async(self, account: TelegramAccount, channel_ref: str, parameters: dict[str, object], target_dir: Path) -> list[dict[str, object]]:
        client = TelegramClient(StringSession(self.decrypt(account.session_encrypted or "")), account.api_id, self.decrypt(account.api_hash_encrypted))
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise ValueError("Telegram 登录会话已失效，请重新登录")
            channel = await self._resolve_channel(client, channel_ref)
            date_from = self._parse_datetime(parameters.get("date_from"))
            date_to = self._parse_datetime(parameters.get("date_to"))
            media_types = {str(item) for item in parameters.get("media_types", ["image", "video"])}
            hashtags = [str(item) for item in parameters.get("hashtags", [])]
            keywords = [str(item) for item in parameters.get("caption_keywords", [])]
            limit = int(parameters.get("max_messages") or 1000)
            target_dir.mkdir(parents=True, exist_ok=True)
            records: list[dict[str, object]] = []
            async for message in client.iter_messages(channel, limit=limit):
                if not message.media:
                    continue
                media_type = "image" if message.photo else "video" if message.video else None
                if media_type is None:
                    continue
                published_at = message.date.astimezone(timezone.utc)
                caption = message.message or ""
                parsed_tags = extract_hashtags(caption)
                if not media_matches(
                    published_at=published_at, media_type=media_type, caption=caption, hashtags=parsed_tags,
                    date_from=date_from, date_to=date_to, allowed_media_types=media_types,
                    required_hashtags=hashtags, required_keywords=keywords,
                ):
                    continue
                if bool(getattr(channel, "noforwards", False) or getattr(message, "noforwards", False)):
                    records.append(self._record(message, channel, media_type, caption, parsed_tags, None, True))
                    continue
                path = target_dir / f"{getattr(channel, 'id', 'channel')}-{message.id}"
                downloaded = await client.download_media(message, file=str(path))
                if not downloaded:
                    continue
                media_path = Path(downloaded)
                if media_path.stat().st_size > self.settings.telegram_max_media_bytes:
                    media_path.unlink(missing_ok=True)
                    raise ValueError("Telegram 媒体超过下载大小上限")
                records.append(self._record(message, channel, media_type, caption, parsed_tags, media_path, False))
            return records
        except FloodWaitError as exc:
            if exc.seconds > self.settings.telegram_flood_wait_max_seconds:
                raise ValueError(f"Telegram 限流等待时间过长：{exc.seconds} 秒") from exc
            await asyncio.sleep(exc.seconds)
            raise ValueError("Telegram 限流，请重新运行采集任务") from exc
        finally:
            await client.disconnect()

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    async def _resolve_channel(client: TelegramClient, channel_ref: str) -> Any:
        normalized = channel_ref.strip()
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
        return await client.get_entity(normalized)

    @staticmethod
    def _record(message: Any, channel: Any, media_type: str, caption: str, tags: list[tuple[str, str]], path: Path | None, protected: bool) -> dict[str, object]:
        username = getattr(channel, "username", None)
        channel_id = str(getattr(channel, "id", ""))
        return {
            "external_key": f"{channel_id}:{message.id}:0",
            "source_url": f"https://t.me/{username}/{message.id}" if username else f"tg://resolve?domain={channel_id}&post={message.id}",
            "filename": path.name if path else f"telegram-{channel_id}-{message.id}",
            "path": path,
            "channel_id": channel_id,
            "channel_title": getattr(channel, "title", None),
            "channel_username": username,
            "message_id": message.id,
            "grouped_id": str(message.grouped_id) if message.grouped_id else None,
            "media_type": media_type,
            "published_at": as_shanghai_naive(message.date),
            "edited_at": as_shanghai_naive(message.edit_date) if message.edit_date else None,
            "caption": caption or None,
            "hashtags": tags,
            "protected_content": protected,
        }
