"""Tests for yttranscript.config."""

from __future__ import annotations

from pathlib import Path

from yttranscript import config
from yttranscript.config import (
    DEFAULTS,
    _CONFIG_EXAMPLES,
    _CONFIG_HIDDEN,
    _toml_value,
    generate_config_template,
    resolve_value,
)


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
