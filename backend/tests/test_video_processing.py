import shutil
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.video_processing import extract_video_cover_frame


@pytest.mark.parametrize(("codec", "encoder"), [("h264", "libx264"), ("hevc", "libx265")])
def test_invalid_color_metadata_can_still_generate_cover(tmp_path, codec, encoder):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("真实封面解码测试需要 FFmpeg")
    source = tmp_path / "invalid-color.mp4"
    cover = tmp_path / "cover.jpg"
    command = [
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=96x64:rate=10:duration=3", "-c:v", encoder, "-g", "10",
    ]
    if codec == "hevc":
        command += ["-x265-params", "pools=1:frame-threads=1:log-level=error"]
    command += ["-bsf:v", f"{codec}_metadata=matrix_coefficients=3", str(source)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    original = source.read_bytes()

    assert extract_video_cover_frame(ffmpeg, source, cover, capture_at=1.2, duration_seconds=3)

    with Image.open(cover) as image:
        assert image.width > 0 and image.height > 0
    assert source.read_bytes() == original


def test_other_decode_failures_do_not_trigger_color_repair(monkeypatch, tmp_path):
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stderr="Invalid data found when processing input", stdout="")

    monkeypatch.setattr("app.services.video_processing.subprocess.run", fail)

    assert not extract_video_cover_frame("ffmpeg", tmp_path / "broken.mp4", tmp_path / "cover.jpg")
    assert len(calls) == 1
