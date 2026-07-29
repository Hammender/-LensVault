from __future__ import annotations


def format_timestamp(seconds: float) -> str:
    millis = max(round(seconds * 1000), 0)
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def vtt_timestamp_to_srt(timestamp: str) -> str:
    return timestamp.replace(".", ",", 1)


def format_duration(seconds: float) -> str:
    total_seconds = max(round(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def sanitize_vtt_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip())
