"""Configuration loading and resolution from XDG config dir."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from .log import warn


def _config_dir() -> Path:
    """Resolve the config dir honoring $XDG_CONFIG_HOME (XDG Base Dir spec)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "yttranscript"
    return Path.home() / ".config" / "yttranscript"


CONFIG_PATH = _config_dir() / "config.toml"

DEFAULTS = {
    "lang": None,
    "format": "txt",
    "timestamps": False,
    "chunk_size": 30,
    "summarize_cmd": None,
    "summarize_prompt": "Summarize this video transcript in bullet points",
    "summarize_timeout": 300,
    "fallback_lang": "en",
    "whisper_model": "base",
    "whisper_device": "gpu",
    "whisper_dir": None,
    "port": 8080,
    "output": None,
}

# Keys not shown in --show-config / config template (CLI-only or runtime-only).
_CONFIG_HIDDEN = {"output", "port"}

# Example values used when generating the config template (single source of
# truth: DEFAULTS). Only override where a more illustrative example helps.
_CONFIG_EXAMPLES = {
    "lang": "es",
    "summarize_cmd": "llama-cli -m ~/models/gemma-4-E2B-it-NVFP4.gguf -ngl 99 -fa 1 -ub 1024 -b 1024 --single-turn",
    "summarize_prompt": "Resume el video en castellano. Formatealo para que sea facil de leer y respete la normativa de markdown",
    "whisper_dir": "/home/user/.cache/whisper",
}


def _toml_value(val) -> str:
    """Format a Python value as a TOML literal for the config template."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return f'"{val}"'


def generate_config_template() -> str:
    """Generate config template from DEFAULTS (single source of truth)."""
    lines = [
        "# yttranscript configuration",
        "# Uncomment and edit the lines below to set your defaults.",
        "# CLI flags always override these values.",
        "",
    ]
    for key, default in DEFAULTS.items():
        if key in _CONFIG_HIDDEN:
            continue
        example = _CONFIG_EXAMPLES.get(key, default)
        lines.append(f"# {key} = {_toml_value(example)}")
    return "\n".join(lines) + "\n"


DEFAULT_CONFIG = generate_config_template()


def ensure_config_dir() -> None:
    """Create config directory and default config file on first run."""
    config_dir = CONFIG_PATH.parent
    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG, encoding="utf-8")


def load_config() -> dict:
    """Load config from CONFIG_PATH. Returns {} on parse failure."""
    ensure_config_dir()
    if tomllib is None:
        return {}
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        warn(f"Could not parse config file ({CONFIG_PATH}): {e}")
        return {}


def resolve_value(arg_value, config: dict, key: str):
    """Resolve a value: CLI arg > config > default."""
    if arg_value is not None:
        return arg_value
    return config.get(key, DEFAULTS.get(key))


def hidden_keys() -> set[str]:
    """Return the set of keys hidden from --show-config / templates."""
    return _CONFIG_HIDDEN
