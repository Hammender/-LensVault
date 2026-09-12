from __future__ import annotations

from app.core.config import Settings
from app.services import subtitles as subtitle_mod
from app.services.subtitles import SubtitleService


class FakeProcess:
    pid = 4321

    def poll(self) -> int | None:
        return None


def test_llama_server_starts_with_error_only_verbosity(tmp_path, monkeypatch) -> None:
    server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    log_path = tmp_path / "logs" / "subtitle-llama-server.log"
    server.write_bytes(b"")
    model.write_bytes(b"")

    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        data_dir=tmp_path,
        subtitle_llama_server_path=server,
        subtitle_translation_model_path=model,
        subtitle_llama_server_log_path=log_path,
        subtitle_llama_server_log_verbosity=1,
    )
    captured: dict[str, object] = {}

    def fake_popen(args, stdout=None, stderr=None, creationflags=0):
        captured["args"] = list(args)
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        log_path.write_text("started\n", encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(subtitle_mod, "_llama_process", None)
    monkeypatch.setattr(subtitle_mod, "_llama_log_handle", None)
    monkeypatch.setattr(subtitle_mod.subprocess, "Popen", fake_popen)

    service = SubtitleService(storage=object(), settings=settings)
    health_calls = {"count": 0}

    def fake_health() -> bool:
        health_calls["count"] += 1
        return health_calls["count"] >= 3

    monkeypatch.setattr(service, "_health_ok", fake_health)
    try:
        service._ensure_translation_server()
    finally:
        subtitle_mod.SubtitleService._close_llama_log_handle()
        subtitle_mod._llama_process = None

    args = captured["args"]
    assert isinstance(args, list)
    assert args[args.index("--verbosity") + 1] == "1"
    assert captured["stdout"] is not None
    assert captured["stdout"] is captured["stderr"]
    assert log_path.exists()
    assert log_path.stat().st_size < 64
