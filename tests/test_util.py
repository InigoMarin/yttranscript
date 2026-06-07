"""Tests for yttranscript.util."""

from __future__ import annotations

import subprocess

import pytest

from yttranscript.util import (
    command_exists,
    confirm,
    is_playlist_url,
    is_youtube_url,
    run,
    sanitize_filename,
    TranscriptError,
)


# --- is_youtube_url -------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtube.com/watch?v=abc",
    "https://m.youtube.com/watch?v=abc&t=10",
    "https://youtu.be/abc",
    "https://www.youtube.com/shorts/abc",
    "https://www.youtube.com/embed/abc",
    "https://www.youtube.com/live/abc",
    "https://www.youtube.com/playlist?list=PL123",
    "https://www.youtube.com/@channelname",
    "https://www.youtube.com/channel/UC123",
    "https://music.youtube.com/watch?v=abc",
    "https://www.youtube-nocookie.com/embed/abc",
    "http://youtube.com/watch?v=abc",
    "HTTPS://WWW.YOUTUBE.COM/watch?v=abc",
])
def test_url_accepts_youtube(url):
    assert is_youtube_url(url)


@pytest.mark.parametrize("url", [
    None,
    "",
    "not a url",
    "/local/path",
    "ftp://youtube.com/x",
    "https://example.com/",
    "https://evil.com/youtube.com/watch",
    "javascript:alert(1)",
    "https://vimeo.com/12345",
    "https://youtube.com.evil.com/watch",
])
def test_url_rejects_non_youtube(url):
    assert not is_youtube_url(url)


# --- is_playlist_url ------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc&list=PL123",
    "https://www.youtube.com/playlist?list=PL123",
])
def test_playlist_url_detected(url):
    assert is_playlist_url(url)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    None,
    "",
])
def test_playlist_url_rejected(url):
    assert not is_playlist_url(url)


# --- TranscriptError ------------------------------------------------------

def test_transcript_error_is_exception():
    assert issubclass(TranscriptError, Exception)
    e = TranscriptError("test")
    assert str(e) == "test"


# --- sanitize_filename ----------------------------------------------------

@pytest.mark.parametrize("title, expected", [
    ("hello", "hello"),
    ("a/b:c?d", "a-b-c-d"),
    ("", "transcript"),
    ('a"b|c*', "a-b-c-"),
    ("日本語", "日本語"),  # unicode preserved
])
def test_sanitize_filename(title, expected):
    assert sanitize_filename(title) == expected


def test_sanitize_filename_truncates_long_titles():
    long_title = "A" * 300
    result = sanitize_filename(long_title)
    assert len(result) == 200


def test_sanitize_filename_strips_dots():
    assert sanitize_filename("..test..") == "test"
    assert sanitize_filename("test.") == "test"


# --- command_exists -------------------------------------------------------

def test_command_exists_python():
    assert command_exists("python") or command_exists("python3")


def test_command_exists_rejects_bogus():
    assert not command_exists("nonexistent_xyz_command_12345")


# --- run ------------------------------------------------------------------

def test_run_captures_output():
    r = run(["echo", "hi"], capture=True, check=False)
    assert r.returncode == 0
    assert r.stdout.strip() == "hi"


def test_run_timeout_raises():
    with pytest.raises(subprocess.TimeoutExpired):
        run(["sleep", "5"], timeout=0.3, check=False)


def test_run_timeout_ok_for_fast_command():
    r = run(["true"], timeout=5, capture=True, check=False)
    assert r.returncode == 0


def test_run_check_raises_on_failure():
    with pytest.raises(subprocess.CalledProcessError):
        run(["false"], check=True)


def test_run_no_check_returns_nonzero():
    r = run(["false"], check=False, capture=True)
    assert r.returncode != 0


# --- confirm --------------------------------------------------------------

def test_confirm_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert confirm("test?") is True


def test_confirm_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert confirm("test?") is False


def test_confirm_default_on_empty(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert confirm("test?", default=True) is True
    assert confirm("test?", default=False) is False


def test_confirm_eof_returns_default(monkeypatch):
    def raise_eof(_):
        raise EOFError()
    monkeypatch.setattr("builtins.input", raise_eof)
    assert confirm("test?", default=True) is True


def test_confirm_keyboard_interrupt_returns_default(monkeypatch):
    def raise_ki(_):
        raise KeyboardInterrupt()
    monkeypatch.setattr("builtins.input", raise_ki)
    assert confirm("test?", default=False) is False
