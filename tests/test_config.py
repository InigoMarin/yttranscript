"""Tests for yttranscript.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from yttranscript import config
from yttranscript.config import (
    DEFAULTS,
    _CONFIG_EXAMPLES,
    _CONFIG_HIDDEN,
    _toml_value,
    generate_config_template,
    resolve_value,
    load_channels,
    resolve_channel_group,
)
from yttranscript.util import TranscriptError


# --- XDG_CONFIG_HOME ------------------------------------------------------

def test_config_path_xdg_default(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    path = config._config_dir()
    assert path == Path.home() / ".config" / "yttranscript"


def test_config_path_xdg_custom(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = config._config_dir()
    assert path == tmp_path / "yttranscript"


def test_config_path_xdg_relative_is_used_as_is(monkeypatch):
    """A relative XDG_CONFIG_HOME is used literally (per spec it should be
    absolute, but we don't enforce that — just verify it's used)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    path = config._config_dir()
    assert path == Path("relative/path") / "yttranscript"


# --- resolve_value --------------------------------------------------------

def test_resolve_value_priority_cli_over_config():
    cfg = {"lang": "es"}
    assert resolve_value("fr", cfg, "lang") == "fr"


def test_resolve_value_priority_config_over_default():
    cfg = {"lang": "es"}
    assert resolve_value(None, cfg, "lang") == "es"


def test_resolve_value_falls_back_to_default():
    assert resolve_value(None, {}, "chunk_size") == DEFAULTS["chunk_size"]


def test_resolve_value_lang_default_is_none():
    assert resolve_value(None, {}, "lang") is None


def test_resolve_value_unknown_key():
    assert resolve_value(None, {}, "nonexistent") is None


# --- config template ------------------------------------------------------

def test_template_includes_all_non_hidden_keys():
    tmpl = generate_config_template()
    for key in DEFAULTS:
        if key in _CONFIG_HIDDEN:
            assert f"# {key} =" not in tmpl, f"hidden key {key} leaked into template"
        else:
            assert f"# {key} =" in tmpl, f"missing key {key} in template"


def test_template_uses_example_values():
    tmpl = generate_config_template()
    for key, val in _CONFIG_EXAMPLES.items():
        if isinstance(val, str):
            assert val in tmpl, f"example value for {key} missing from template"


def test_template_everything_commented_out():
    """All key=value lines start with '#' so the template is opt-in."""
    tmpl = generate_config_template()
    for line in tmpl.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            # Allow human-text lines like "Uncomment and edit..."
            assert any(word in line for word in ("yttranscript", "Uncomment", "CLI")), (
                f"uncommented assignment in template: {line!r}"
            )


def test_toml_value_formatting():
    assert _toml_value(True) == "true"
    assert _toml_value(False) == "false"
    assert _toml_value(42) == "42"
    assert _toml_value(3.14) == "3.14"
    assert _toml_value("hello") == '"hello"'


def test_toml_value_formats_lists():
    assert _toml_value([]) == "[]"
    assert _toml_value(["a", "b"]) == '["a", "b"]'
    assert _toml_value([True, 1]) == "[true, 1]"


# --- network / anti-block keys present ------------------------------------

@pytest.mark.parametrize("key", [
    "proxy", "cookies", "cookies_from_browser",
    "force_ipv4", "geo_bypass", "extractor_args", "ytdlp_args",
])
def test_defaults_contain_network_key(key):
    assert key in DEFAULTS


def test_defaults_ytdlp_args_is_list():
    assert isinstance(DEFAULTS["ytdlp_args"], list)
    assert DEFAULTS["ytdlp_args"] == []


def test_template_renders_ytdlp_args_as_toml_array():
    tmpl = generate_config_template()
    assert "# ytdlp_args = []" in tmpl


def test_template_renders_force_ipv4_as_bool():
    tmpl = generate_config_template()
    assert "# force_ipv4 = false" in tmpl
    assert "# geo_bypass = false" in tmpl


# --- load_config robustness -----------------------------------------------

def test_load_config_returns_empty_when_tomllib_missing(monkeypatch):
    monkeypatch.setattr(config, "tomllib", None)
    monkeypatch.setattr(config, "ensure_config_dir", lambda: None)
    assert config.load_config() == {}


def test_load_config_malformed_returns_empty(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("this is = not = valid = toml {{{")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config, "ensure_config_dir", lambda: None)
    assert config.load_config() == {}


def test_load_config_parses_valid_toml(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('lang = "es"\nchunk_size = 60\n')
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config, "ensure_config_dir", lambda: None)
    result = config.load_config()
    assert result == {"lang": "es", "chunk_size": 60}


def test_ensure_config_dir_creates_default_file(monkeypatch, tmp_path):
    """ensure_config_dir creates the dir + writes the template if missing."""
    target = tmp_path / "yttranscript" / "config.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", target)
    config.ensure_config_dir()
    assert target.exists()
    assert "yttranscript configuration" in target.read_text()


# --- load_channels ---------------------------------------------------------

def test_load_channels_returns_empty_when_none(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('lang = "es"\n')
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config, "ensure_config_dir", lambda: None)
    assert load_channels() == {}


def test_load_channels_returns_groups(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[channels]\n'
        'tech = ["https://www.youtube.com/@Fireship"]\n'
        'news = ["https://www.youtube.com/@BBCNews"]\n'
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config, "ensure_config_dir", lambda: None)
    result = load_channels()
    assert result == {
        "tech": ["https://www.youtube.com/@Fireship"],
        "news": ["https://www.youtube.com/@BBCNews"],
    }


# --- resolve_channel_group --------------------------------------------------

def test_resolve_channel_group_found():
    cfg = {"channels": {"tech": ["https://www.youtube.com/@Fireship"]}}
    assert resolve_channel_group(cfg, "tech") == ["https://www.youtube.com/@Fireship"]


def test_resolve_channel_group_not_found_raises():
    cfg = {"channels": {"tech": ["https://www.youtube.com/@Fireship"]}}
    with pytest.raises(TranscriptError, match="tech2.*Available groups: tech"):
        resolve_channel_group(cfg, "tech2")


def test_resolve_channel_group_empty_config_raises():
    with pytest.raises(TranscriptError, match="Available groups:.*none"):
        resolve_channel_group({}, "missing")


# --- template includes channels section ------------------------------------

def test_template_includes_channels_section():
    tmpl = generate_config_template()
    assert "[channels]" in tmpl
