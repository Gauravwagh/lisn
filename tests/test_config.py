import pytest

from lisn.config import Config, load_config, save_config, set_value
from lisn.errors import ConfigError


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    assert load_config(path) == Config()
    updated = set_value(Config(), "speed", "1.3")
    updated = set_value(updated, "voice", "am_michael")
    updated = set_value(updated, "autoscroll", "false")
    save_config(updated, path)
    loaded = load_config(path)
    assert loaded.speed == 1.3 and loaded.voice == "am_michael" and loaded.autoscroll is False


def test_validation():
    with pytest.raises(ConfigError):
        set_value(Config(), "speed", "9")
    with pytest.raises(ConfigError):
        set_value(Config(), "highlight", "letter")
    with pytest.raises(ConfigError):
        set_value(Config(), "nope", "x")
    with pytest.raises(ConfigError):
        set_value(Config(), "prefetch", "abc")


def test_overrides_skip_none():
    cfg = Config().with_overrides(voice=None, speed=2.0)
    assert cfg.voice == "af_heart" and cfg.speed == 2.0


def test_bad_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1,2]")
    with pytest.raises(ConfigError):
        load_config(path)
