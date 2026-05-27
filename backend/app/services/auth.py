from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone


PASSWORD_ITERATIONS = 260_000


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations, salt, expected = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _b64decode(salt), int(iterations))
        return hmac.compare_digest(_b64encode(digest), expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, secret: str, expires_minutes: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": str(user_id), "exp": int(expires_at.timestamp())}
    signing_input = f"{_b64encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64encode(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(token: str, secret: str) -> int | None:
    try:
        header, payload, signature = token.split(".", 2)
        signing_input = f"{header}.{payload}"
        expected = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64encode(expected), signature):
            return None
        data = json.loads(_b64decode(payload))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return int(data["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
