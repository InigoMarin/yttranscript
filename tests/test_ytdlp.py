"""Tests for yttranscript.ytdlp: mocked subprocess wrappers."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from yttranscript.util import TranscriptError
from yttranscript.ytdlp import (
    TIMEOUT_METADATA,
    TIMEOUT_SUBTITLE,
    detect_video_language,
    ensure_yt_dlp,
    ensure_whisper,
    get_lang_variants,
    get_video_info,
    get_video_title,
    list_channel_videos,
    list_subs,
    resolve_channel_videos,
    try_download_subtitle,
)


def _cp(returncode=0, stdout="", stderr=""):
    """Build a CompletedProcess for mocking."""
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# --- get_lang_variants (pure logic) ---------------------------------------

@pytest.mark.parametrize("lang, expected", [
    ("es", ["es", "es.*"]),
    ("es-MX", ["es-MX", "es", "es.*"]),
    ("en-US", ["en-US", "en", "en.*"]),
    ("pt", ["pt", "pt.*"]),
    ("de", ["de", "de.*"]),
])
def test_get_lang_variants(lang, expected):
    assert get_lang_variants(lang) == expected


# --- get_video_title ------------------------------------------------------

def test_get_video_title_success():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "My Cool Video\n")):
        assert get_video_title("https://youtube.com/watch?v=x") == "My Cool Video"


def test_get_video_title_sanitizes():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "a/b:c?d\n")):
        assert get_video_title("u") == "a-b-c-d"


def test_get_video_title_failure_fallback():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        assert get_video_title("u") == "transcript"


def test_get_video_title_uses_metadata_timeout():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "T\n")) as m:
        get_video_title("u")
        assert m.call_args.kwargs.get("timeout") == TIMEOUT_METADATA


# --- get_video_info -------------------------------------------------------

def test_get_video_info_success():
    raw = "120|5000000|My Title"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info == {"duration": 120, "size": 5000000, "title": "My Title"}


def test_get_video_info_handles_na_values():
    raw = "NA|NA|Title"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["duration"] == 0
        assert info["size"] == 0
        assert info["title"] == "Title"


def test_get_video_info_failure():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        info = get_video_info("u")
        assert info == {"duration": 0, "size": 0, "title": "unknown"}


def test_get_video_info_title_with_pipe_preserved():
    """Titles containing | are kept intact (split limit prevents corruption)."""
    raw = "60|1000|Cool Video | Part 1 | HD"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["title"] == "Cool Video | Part 1 | HD"


def test_get_video_info_handles_float_duration():
    raw = "90.7|0|T"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["duration"] == 90


# --- detect_video_language ------------------------------------------------

def test_detect_language_success():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "en-US\n")):
        assert detect_video_language("u") == "en"


def test_detect_language_simple_code():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "es\n")):
        assert detect_video_language("u") == "es"


def test_detect_language_na_returns_none():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "NA\n")):
        assert detect_video_language("u") is None


def test_detect_language_empty_returns_none():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "\n")):
        assert detect_video_language("u") is None


def test_detect_language_failure_returns_none():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        assert detect_video_language("u") is None


# --- try_download_subtitle ------------------------------------------------

def test_try_download_subtitle_success(tmp_path):
    prefix = str(tmp_path / "transcript_temp")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")):
        # Simulate yt-dlp creating a VTT file
        (tmp_path / "transcript_temp.en.vtt").write_text("WEBVTT\n")
        result = try_download_subtitle("u", prefix, "en", use_auto=False,
                                       work_dir=tmp_path)
        assert result is True


def test_try_download_subtitle_no_vtt_created(tmp_path):
    prefix = str(tmp_path / "transcript_temp")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")):
        result = try_download_subtitle("u", prefix, "en", use_auto=False,
                                       work_dir=tmp_path)
        assert result is False


def test_try_download_subtitle_ytdlp_failure(tmp_path):
    prefix = str(tmp_path / "transcript_temp")
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "error")):
        result = try_download_subtitle("u", prefix, "en", use_auto=True,
                                       work_dir=tmp_path)
        assert result is False


def test_try_download_subtitle_uses_subtitle_timeout(tmp_path):
    prefix = str(tmp_path / "t")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m:
        try_download_subtitle("u", prefix, "en", use_auto=False, work_dir=tmp_path)
        assert m.call_args.kwargs.get("timeout") == TIMEOUT_SUBTITLE


def test_try_download_subtitle_auto_flag_adds_write_auto_sub(tmp_path):
    prefix = str(tmp_path / "t")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m:
        try_download_subtitle("u", prefix, "en", use_auto=True, work_dir=tmp_path)
        cmd = m.call_args.args[0]
        assert "--write-auto-sub" in cmd
        assert "--write-sub" not in cmd


def test_try_download_subtitle_manual_flag_adds_write_sub(tmp_path):
    prefix = str(tmp_path / "t")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m:
        try_download_subtitle("u", prefix, "en", use_auto=False, work_dir=tmp_path)
        cmd = m.call_args.args[0]
        assert "--write-sub" in cmd
        assert "--write-auto-sub" not in cmd


def test_try_download_subtitle_cwd_fallback(tmp_path, monkeypatch):
    """When work_dir=None, search in CWD."""
    monkeypatch.chdir(tmp_path)
    prefix = "transcript_temp"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")):
        (tmp_path / "transcript_temp.en.vtt").write_text("WEBVTT\n")
        result = try_download_subtitle("u", prefix, "en", use_auto=False,
                                       work_dir=None)
        assert result is True


# --- list_subs ------------------------------------------------------------

def test_list_subs_calls_ytdlp(capsys):
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "en (manual)\n")):
        list_subs("u")
        captured = capsys.readouterr()
        assert "Available subtitles" in captured.err or "Available subtitles" in captured.out


# --- ensure_yt_dlp --------------------------------------------------------

def test_ensure_yt_dlp_already_installed():
    with patch("yttranscript.ytdlp.command_exists", return_value=True):
        ensure_yt_dlp()  # should be a no-op


def test_ensure_yt_dlp_install_via_pip_success():
    """pip is tried first; on success yt-dlp is available and no sudo is used."""
    yt_dlp_checks = {"n": 0}

    def fake_command_exists(cmd):
        if cmd == "yt-dlp":
            yt_dlp_checks["n"] += 1
            return yt_dlp_checks["n"] >= 2
        return False

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m_run, \
         patch("yttranscript.ytdlp.confirm") as m_confirm:
        ensure_yt_dlp()
        m_confirm.assert_not_called()
        for call_args in m_run.call_args_list:
            assert "sudo" not in call_args.args[0]


def test_ensure_yt_dlp_pip_fails_falls_back_to_apt():
    """pip install fails -> apt available -> confirm yes -> sudo apt runs."""
    yt_dlp_checks = {"n": 0}

    def fake_command_exists(cmd):
        if cmd == "yt-dlp":
            yt_dlp_checks["n"] += 1
            return yt_dlp_checks["n"] >= 2
        if cmd == "apt":
            return True
        return False

    def fake_run(cmd, **kwargs):
        if "pip" in cmd and "install" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run, \
         patch("yttranscript.ytdlp.confirm", return_value=True) as m_confirm:
        ensure_yt_dlp()
        m_confirm.assert_called_once()
        assert "sudo password" in m_confirm.call_args.args[0]
        sudo_calls = [c for c in m_run.call_args_list if "sudo" in c.args[0]]
        assert len(sudo_calls) == 2


def test_ensure_yt_dlp_pip_fails_apt_declined():
    """pip fails -> apt confirm returns False -> TranscriptError, no sudo."""
    def fake_command_exists(cmd):
        if cmd == "apt":
            return True
        return False

    def fake_run(cmd, **kwargs):
        if "pip" in cmd and "install" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run, \
         patch("yttranscript.ytdlp.confirm", return_value=False):
        with pytest.raises(TranscriptError):
            ensure_yt_dlp()
        for call_args in m_run.call_args_list:
            assert "sudo" not in call_args.args[0]


def test_ensure_yt_dlp_pip_unavailable_brew_install():
    """pip not available -> brew available -> confirm yes -> brew install."""
    yt_dlp_checks = {"n": 0}

    def fake_command_exists(cmd):
        if cmd == "yt-dlp":
            yt_dlp_checks["n"] += 1
            return yt_dlp_checks["n"] >= 2
        if cmd == "brew":
            return True
        return False

    def fake_run(cmd, **kwargs):
        if "pip" in cmd and "--version" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run, \
         patch("yttranscript.ytdlp.confirm", return_value=True) as m_confirm:
        ensure_yt_dlp()
        m_confirm.assert_called_once()
        brew_calls = [c for c in m_run.call_args_list
                      if "brew" in c.args[0] and "install" in c.args[0]]
        assert len(brew_calls) == 1


def test_ensure_yt_dlp_pip_unavailable_no_managers():
    """pip not available, no brew/apt -> TranscriptError with manual URL."""
    def fake_run(cmd, **kwargs):
        if "pip" in cmd and "--version" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", return_value=False), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run):
        with pytest.raises(TranscriptError) as exc_info:
            ensure_yt_dlp()
        assert "https://github.com/yt-dlp/yt-dlp#installation" in str(exc_info.value)


def test_ensure_yt_dlp_install_attempted_still_missing():
    """Installs attempted but yt-dlp still not on PATH -> TranscriptError."""
    def fake_command_exists(cmd):
        if cmd == "brew":
            return True
        return False

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", return_value=_cp(0, "")), \
         patch("yttranscript.ytdlp.confirm", return_value=True):
        with pytest.raises(TranscriptError) as exc_info:
            ensure_yt_dlp()
        assert "Failed to install yt-dlp" in str(exc_info.value)


# --- ensure_whisper -------------------------------------------------------

def test_ensure_whisper_already_installed():
    with patch("yttranscript.ytdlp.command_exists", return_value=True):
        assert ensure_whisper() is True


def test_ensure_whisper_user_declines(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    with patch("yttranscript.ytdlp.command_exists", return_value=False):
        assert ensure_whisper() is False


# --- list_channel_videos --------------------------------------------------

def test_list_channel_videos_success(capsys):
    channel_raw = "UC12345678\n"
    videos_raw = "20240115|vid1|First Video\n20240114|vid2|Second Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        result = list_channel_videos("https://youtube.com/@chan", limit=2)
        captured = capsys.readouterr()
        assert "UC12345678" in captured.out
        assert "First Video" in captured.out
    assert result == [("2024-01-15", "vid1", "First Video"),
                      ("2024-01-14", "vid2", "Second Video")]


def test_list_channel_videos_invalid_id_exits():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "NOTUC\n")):
        with pytest.raises(TranscriptError):
            list_channel_videos("u")


def test_list_channel_videos_resolve_failure_exits():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        with pytest.raises(TranscriptError):
            list_channel_videos("u")


# --- resolve_channel_videos ------------------------------------------------

def test_resolve_channel_videos_success():
    channel_raw = "UC12345678\n"
    videos_raw = "20240115|vid1|First Video\n20240114|vid2|Second Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        videos = resolve_channel_videos("https://youtube.com/@chan", limit=2)
    assert videos == [("2024-01-15", "vid1", "First Video"),
                      ("2024-01-14", "vid2", "Second Video")]


def test_resolve_channel_videos_invalid_id_exits():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "NOTUC\n")):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


def test_resolve_channel_videos_resolve_failure_exits():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


def test_resolve_channel_videos_fetch_failure_exits():
    responses = iter([_cp(0, "UC12345678\n"), _cp(1, "")])
    with patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


def test_resolve_channel_videos_skips_malformed_lines():
    channel_raw = "UC12345678\n"
    videos_raw = "badline\n20240115|vid1|First Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        videos = resolve_channel_videos("u")
    assert videos == [("2024-01-15", "vid1", "First Video")]


def test_resolve_channel_videos_empty_fetch_exits():
    responses = iter([_cp(0, "UC12345678\n"), _cp(0, "\n")])
    with patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")
