"""Shared pytest fixtures and path bootstrap."""

import sys
from pathlib import Path

# Ensure the local package is importable when running pytest from the repo
# root without an editable install.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest


@pytest.fixture
def sample_vtt_path(tmp_path) -> Path:
    """A VTT file with realistic cues: HTML tags, entities, repeated lines."""
    p = tmp_path / "sample.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.500\n"
        "Hello world\n"
        "\n"
        "00:00:02.500 --> 00:00:05.000\n"
        "This is a <b>test</b> &amp; demo\n"
        "\n"
        "00:00:05.000 --> 00:00:07.500\n"
        "Hello world\n"
        "\n"
        "00:00:07.500 --> 00:00:10.000\n"
        "Final line &#39;with quotes&#39;\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Run a test with CWD set to a clean tempdir (so glob('./...') is safe)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def reset_log():
    """Reset thread-local log state and VERBOSITY before and after the test."""
    from yttranscript import log
    log._thread_local.__dict__.clear()
    old_v = log.VERBOSITY
    yield log
    log._thread_local.__dict__.clear()
    log.VERBOSITY = old_v
