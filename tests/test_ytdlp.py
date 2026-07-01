"""Tests for yttranscript.ytdlp: mocked subprocess wrappers."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from yttranscript.util import TranscriptError
from yttranscript.ytdlp import (
    TIMEOUT_METADATA,
    TIMEOUT_SUBTITLE,
    ensure_yt_dlp,
    ensure_whisper,
    get_lang_variants,
    get_video_info,
    get_video_metadata,
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
    ("es", ["es.*", "es"]),
    ("es-MX", ["es.*", "es-MX", "es"]),
    ("en-US", ["en.*", "en-US", "en"]),
    ("pt", ["pt.*", "pt"]),
    ("de", ["de.*", "de"]),
])
def test_get_lang_variants(lang, expected):
    assert get_lang_variants(lang) == expected


# --- _parse_upload_date ---------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("20240115", "2024-01-15"),
    ("20231231", "2023-12-31"),
    ("", ""),
    ("short", ""),
    ("123456789", ""),
])
def test_parse_upload_date(raw, expected):
    from yttranscript.ytdlp import _parse_upload_date
    assert _parse_upload_date(raw) == expected


# --- get_video_info -------------------------------------------------------

def test_get_video_info_success():
    raw = "120|5000000|My Title|TestChannel|20240115"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["duration"] == 120
        assert info["size"] == 5000000
        assert info["title"] == "My Title"
        assert info["channel"] == "TestChannel"
        assert info["upload_date"] == "2024-01-15"


def test_get_video_info_handles_na_values():
    raw = "NA|NA|Title"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["duration"] == 0
        assert info["size"] == 0
        assert info["title"] == "Title"
        assert info["channel"] == ""
        assert info["upload_date"] == ""


def test_get_video_info_failure():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        info = get_video_info("u")
        assert info["duration"] == 0
        assert info["size"] == 0
        assert info["title"] == "unknown"
        assert info["channel"] == ""
        assert info["upload_date"] == ""


def test_get_video_info_title_with_pipe_preserved():
    """Titles containing | before the last 2 fields are kept intact."""
    raw = "60|1000|Cool Video - Part 1|TestChannel|20240115"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["title"] == "Cool Video - Part 1"
        assert info["channel"] == "TestChannel"
        assert info["upload_date"] == "2024-01-15"


def test_get_video_info_handles_float_duration():
    raw = "90.7|0|T"
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        info = get_video_info("u")
        assert info["duration"] == 90


# --- get_video_metadata ---------------------------------------------------

def test_get_video_metadata_success():
    import json as _json
    raw = _json.dumps({"title": "My Video", "duration": 120.5,
                       "filesize_approx": 5000000, "language": "en-US"})
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        meta = get_video_metadata("u")
        assert meta["title"] == "My Video"
        assert meta["sanitized_title"] == "My Video"
        assert meta["duration"] == 120
        assert meta["size"] == 5000000
        assert meta["language"] == "en"


def test_get_video_metadata_failure():
    with patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        meta = get_video_metadata("u")
        assert meta["title"] == "unknown"
        assert meta["duration"] == 0
        assert meta["language"] is None


def test_get_video_metadata_na_language():
    import json as _json
    raw = _json.dumps({"title": "T", "duration": 0, "language": "NA"})
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        meta = get_video_metadata("u")
        assert meta["language"] is None


def test_get_video_metadata_invalid_json():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "not json")):
        meta = get_video_metadata("u")
        assert meta["title"] == "unknown"


def test_get_video_metadata_uses_metadata_timeout():
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "{}")) as m:
        get_video_metadata("u")
        assert m.call_args.kwargs.get("timeout") == TIMEOUT_METADATA


def test_get_video_metadata_sanitizes_title():
    import json as _json
    raw = _json.dumps({"title": "a/b:c?d", "duration": 0, "language": "en"})
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        meta = get_video_metadata("u")
        assert meta["sanitized_title"] == "a-b-c-d"


def test_get_video_metadata_no_language():
    import json as _json
    raw = _json.dumps({"title": "T", "duration": 60})
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)):
        meta = get_video_metadata("u")
        assert meta["language"] is None


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


def test_try_download_subtitle_both_flags(tmp_path):
    prefix = str(tmp_path / "t")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m:
        try_download_subtitle("u", prefix, "en", try_both=True, work_dir=tmp_path)
        cmd = m.call_args.args[0]
        assert "--write-sub" in cmd
        assert "--write-auto-sub" in cmd


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


def test_ensure_yt_dlp_install_via_pipx_success():
    """pipx is tried first; on success yt-dlp is available and no sudo is used."""
    yt_dlp_checks = {"n": 0}

    def fake_command_exists(cmd):
        if cmd == "yt-dlp":
            yt_dlp_checks["n"] += 1
            return yt_dlp_checks["n"] >= 2
        if cmd == "pipx":
            return True
        return False

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m_run, \
         patch("yttranscript.ytdlp.confirm") as m_confirm:
        ensure_yt_dlp()
        m_confirm.assert_not_called()
        pipx_calls = [c for c in m_run.call_args_list if "pipx" in c.args[0]]
        assert len(pipx_calls) == 1
        for call_args in m_run.call_args_list:
            assert "sudo" not in call_args.args[0]


def test_ensure_yt_dlp_pipx_fails_falls_back_to_pip():
    """pipx install fails -> pip available -> pip install runs and succeeds."""
    yt_dlp_checks = {"n": 0}

    def fake_command_exists(cmd):
        if cmd == "yt-dlp":
            yt_dlp_checks["n"] += 1
            return yt_dlp_checks["n"] >= 2
        if cmd == "pipx":
            return True
        return False

    def fake_run(cmd, **kwargs):
        if "pipx" in cmd:
            return _cp(1, "pipx error")
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run:
        ensure_yt_dlp()
        pipx_calls = [c for c in m_run.call_args_list if "pipx" in c.args[0]]
        pip_install_calls = [
            c for c in m_run.call_args_list
            if "pip" in c.args[0] and "install" in c.args[0]
        ]
        assert len(pipx_calls) == 1
        assert len(pip_install_calls) == 1


def test_ensure_yt_dlp_pipx_success_but_not_on_path():
    """pipx reports success but yt-dlp not on PATH -> TranscriptError, no pip fallback."""
    def fake_command_exists(cmd):
        if cmd == "pipx":
            return True
        return False  # yt-dlp never appears, even after PATH extension

    def fake_run(cmd, **kwargs):
        if "pipx" in cmd:
            return _cp(0, "")  # pipx succeeds
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run:
        with pytest.raises(TranscriptError) as exc_info:
            ensure_yt_dlp()
        assert "not on your PATH" in str(exc_info.value)
        # pip install must NOT be called (avoids duplicate install)
        pip_install_calls = [
            c for c in m_run.call_args_list
            if "pip" in c.args[0] and "install" in c.args[0]
        ]
        assert len(pip_install_calls) == 0


def test_ensure_yt_dlp_pipx_and_pip_fail_falls_back_to_apt():
    """pipx and pip both fail -> apt available -> confirm yes -> sudo apt runs."""
    yt_dlp_checks = {"n": 0}

    def fake_command_exists(cmd):
        if cmd == "yt-dlp":
            yt_dlp_checks["n"] += 1
            return yt_dlp_checks["n"] >= 2
        if cmd == "pipx":
            return True
        if cmd == "apt":
            return True
        return False

    def fake_run(cmd, **kwargs):
        if "pipx" in cmd:
            return _cp(1, "pipx error")
        if "pip" in cmd and "install" in cmd:
            return _cp(1, "pip error")
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run, \
         patch("yttranscript.ytdlp.confirm", return_value=True) as m_confirm:
        ensure_yt_dlp()
        m_confirm.assert_called_once()
        assert "sudo password" in m_confirm.call_args.args[0]
        sudo_calls = [c for c in m_run.call_args_list if "sudo" in c.args[0]]
        assert len(sudo_calls) == 2


def test_ensure_yt_dlp_pipx_and_pip_fail_apt_declined():
    """pipx and pip both fail -> apt confirm returns False -> TranscriptError, no sudo."""
    def fake_command_exists(cmd):
        if cmd == "pipx":
            return True
        if cmd == "apt":
            return True
        return False

    def fake_run(cmd, **kwargs):
        if "pipx" in cmd:
            return _cp(1, "pipx error")
        if "pip" in cmd and "install" in cmd:
            return _cp(1, "pip error")
        return _cp(0, "")

    with patch("yttranscript.ytdlp.command_exists", side_effect=fake_command_exists), \
         patch("yttranscript.ytdlp.run", side_effect=fake_run) as m_run, \
         patch("yttranscript.ytdlp.confirm", return_value=False):
        with pytest.raises(TranscriptError):
            ensure_yt_dlp()
        for call_args in m_run.call_args_list:
            assert "sudo" not in call_args.args[0]


def test_ensure_yt_dlp_no_pipx_no_pip_brew_install():
    """pipx and pip both unavailable -> brew available -> confirm yes -> brew install."""
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


def test_ensure_yt_dlp_no_pipx_no_pip_no_managers():
    """pipx and pip unavailable, no brew/apt -> TranscriptError with manual URL."""
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
    channel_raw = "UC12345678|My Channel\n"
    videos_raw = "20240115|vid1|First Video\n20240114|vid2|Second Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        result = list_channel_videos("https://youtube.com/@chan", limit=2)
        captured = capsys.readouterr()
        assert "My Channel" in captured.out
        assert "First Video" in captured.out
    assert result == ("My Channel", [("2024-01-15", "vid1", "First Video"),
                                     ("2024-01-14", "vid2", "Second Video")])


def test_list_channel_videos_invalid_id_exits():
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", return_value=_cp(0, "NOTUC|Bad\n")):
        with pytest.raises(TranscriptError):
            list_channel_videos("u")


def test_list_channel_videos_resolve_failure_exits():
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        with pytest.raises(TranscriptError):
            list_channel_videos("u")


# --- resolve_channel_videos ------------------------------------------------

def test_resolve_channel_videos_success():
    channel_raw = "UC12345678|My Channel\n"
    videos_raw = "20240115|vid1|First Video\n20240114|vid2|Second Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        channel_name, videos = resolve_channel_videos("https://youtube.com/@chan", limit=2)
    assert channel_name == "My Channel"
    assert videos == [("2024-01-15", "vid1", "First Video"),
                      ("2024-01-14", "vid2", "Second Video")]


def test_resolve_channel_videos_calls_ensure_yt_dlp():
    """Regression: --latest/--group paths must auto-install yt-dlp when missing."""
    channel_raw = "UC12345678|My Channel\n"
    videos_raw = "20240115|vid1|First Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.ensure_yt_dlp") as mock_ensure, \
         patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        resolve_channel_videos("u")
    mock_ensure.assert_called_once()


def test_resolve_channel_videos_invalid_id_exits():
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", return_value=_cp(0, "NOTUC|Bad\n")):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


def test_resolve_channel_videos_resolve_failure_exits():
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", return_value=_cp(1, "")):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


def test_resolve_channel_videos_fetch_failure_exits():
    responses = iter([_cp(0, "UC12345678|Chan\n"), _cp(1, "")])
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


def test_resolve_channel_videos_skips_malformed_lines():
    channel_raw = "UC12345678|My Channel\n"
    videos_raw = "badline\n20240115|vid1|First Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        channel_name, videos = resolve_channel_videos("u")
    assert channel_name == "My Channel"
    assert videos == [("2024-01-15", "vid1", "First Video")]


def test_resolve_channel_videos_empty_fetch_exits():
    responses = iter([_cp(0, "UC12345678|Chan\n"), _cp(0, "\n")])
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run", side_effect=lambda *a, **kw: next(responses)):
        with pytest.raises(TranscriptError):
            resolve_channel_videos("u")


# --- NetworkOpts ----------------------------------------------------------

def test_network_opts_empty_renders_nothing():
    from yttranscript.ytdlp import NetworkOpts, NO_NETWORK
    assert NetworkOpts().to_ytdlp_args() == []
    assert NO_NETWORK.to_ytdlp_args() == []
    assert NetworkOpts().is_empty() is True


@pytest.mark.parametrize("opts, expected_prefix", [
    ({"proxy": "socks5://h:1080"}, ["--proxy", "socks5://h:1080"]),
    ({"cookies": "/tmp/cookies.txt"}, ["--cookies", "/tmp/cookies.txt"]),
    ({"cookies_from_browser": "firefox"},
     ["--cookies-from-browser", "firefox"]),
    ({"force_ipv4": True}, ["--force-ipv4"]),
    ({"geo_bypass": True}, ["--geo-bypass"]),
    ({"extractor_args": "youtube:player_client=-android"},
     ["--extractor-args", "youtube:player_client=-android"]),
    ({"extra_args": ["--retries", "10", "--no-progress"]},
     ["--retries", "10", "--no-progress"]),
])
def test_network_opts_renders_each_field(opts, expected_prefix):
    from yttranscript.ytdlp import NetworkOpts
    assert NetworkOpts(**opts).to_ytdlp_args() == expected_prefix


def test_network_opts_combines_all_fields():
    from yttranscript.ytdlp import NetworkOpts
    args = NetworkOpts(
        proxy="http://p:8080",
        cookies="/c.txt",
        cookies_from_browser="chrome",
        force_ipv4=True,
        geo_bypass=True,
        extractor_args="youtube:player_client=web",
        extra_args=["--foo"],
    ).to_ytdlp_args()
    # Stable order regardless of dict construction.
    assert args == [
        "--proxy", "http://p:8080",
        "--cookies", "/c.txt",
        "--cookies-from-browser", "chrome",
        "--force-ipv4",
        "--geo-bypass",
        "--extractor-args", "youtube:player_client=web",
        "--foo",
    ]


def test_network_opts_is_empty_false_when_any_set():
    from yttranscript.ytdlp import NetworkOpts
    assert NetworkOpts(force_ipv4=True).is_empty() is False
    assert NetworkOpts(extra_args=["--x"]).is_empty() is False


# --- network propagation into yt-dlp calls --------------------------------

def _capture_cmd(mock_run):
    """Pull the first positional argv from the first call to `run`."""
    return mock_run.call_args.args[0]


def test_get_video_metadata_forwards_network():
    from yttranscript.ytdlp import NetworkOpts
    import json as _json
    raw = _json.dumps({"title": "T", "duration": 0})
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)) as m:
        get_video_metadata("u", network=NetworkOpts(proxy="socks5://x"))
    cmd = _capture_cmd(m)
    assert "--proxy" in cmd and "socks5://x" in cmd
    assert cmd[-1] == "u"  # URL stays last


def test_list_subs_forwards_network(capsys):
    from yttranscript.ytdlp import NetworkOpts
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "en\n")) as m:
        list_subs("u", network=NetworkOpts(force_ipv4=True))
    cmd = _capture_cmd(m)
    assert "--force-ipv4" in cmd


def test_get_video_info_forwards_network():
    from yttranscript.ytdlp import NetworkOpts
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "0|0|T|C|20240101")) as m:
        get_video_info("u", network=NetworkOpts(extractor_args="youtube:x=y"))
    cmd = _capture_cmd(m)
    assert "--extractor-args" in cmd and "youtube:x=y" in cmd


def test_try_download_subtitle_forwards_network(tmp_path):
    from yttranscript.ytdlp import NetworkOpts
    prefix = str(tmp_path / "t")
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, "")) as m:
        try_download_subtitle(
            "u", prefix, "en", use_auto=False, work_dir=tmp_path,
            network=NetworkOpts(proxy="socks5://h:1080", force_ipv4=True),
        )
    cmd = _capture_cmd(m)
    assert "--proxy" in cmd and "socks5://h:1080" in cmd
    assert "--force-ipv4" in cmd
    # Network args must come AFTER the yt-dlp specific options but BEFORE URL.
    assert cmd.index("--force-ipv4") < cmd.index("u")
    assert cmd.index("--sub-langs") < cmd.index("--proxy")


def test_resolve_channel_videos_forwards_network_to_both_calls():
    from yttranscript.ytdlp import NetworkOpts
    channel_raw = "UC12345678|My Channel\n"
    videos_raw = "20240115|vid1|First Video\n"
    responses = iter([_cp(0, channel_raw), _cp(0, videos_raw)])
    with patch("yttranscript.ytdlp.ensure_yt_dlp"), \
         patch("yttranscript.ytdlp.run",
               side_effect=lambda *a, **kw: next(responses)) as m:
        resolve_channel_videos(
            "u", network=NetworkOpts(proxy="socks5://x"),
        )
    assert len(m.call_args_list) == 2
    for call in m.call_args_list:
        cmd = call.args[0]
        assert "--proxy" in cmd and "socks5://x" in cmd


def test_calls_omit_network_args_when_none():
    """Backward-compat: no NetworkOpts → no extra argv."""
    import json as _json
    raw = _json.dumps({"title": "T"})
    with patch("yttranscript.ytdlp.run", return_value=_cp(0, raw)) as m:
        get_video_metadata("u")
    cmd = _capture_cmd(m)
    assert cmd == ["yt-dlp", "-j", "-f", "bestaudio", "u"]
