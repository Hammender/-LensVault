from pathlib import Path

import pytest

from app.core import config


PACKAGE_DEFAULTS = {
    "VIDEO_PACKAGE_MAX_FILE_BYTES": 17179869184,
    "VIDEO_PACKAGE_MAX_TOTAL_BYTES": 137438953472,
    "VIDEO_PACKAGE_MAX_COMPRESSION_RATIO": 200,
    "VIDEO_PACKAGE_UPLOAD_MAX_BYTES": 137438953472,
}


def test_env_example_contains_video_package_defaults():
    example = Path(__file__).resolve().parents[2] / ".env.example"
    values = dict(line.split("=", 1) for line in example.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.lstrip().startswith("#") and "=" in line)
    for key, expected in PACKAGE_DEFAULTS.items():
        assert int(values[key]) == expected
        assert config.Settings.model_fields[key.lower()].default == expected


@pytest.mark.parametrize("missing_key", PACKAGE_DEFAULTS)
def test_runtime_still_requires_all_package_settings(monkeypatch, missing_key):
    keys = {name.upper() for name in config.Settings.model_fields} - {missing_key}
    monkeypatch.setattr(config, "_dotenv_keys", lambda _: keys)
    with pytest.raises(RuntimeError, match=missing_key):
        config.get_settings.__wrapped__()
