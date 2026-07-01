"""Tests for yttranscript.whisper: mocked transcription pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from yttranscript.whisper import transcribe_with_whisper, WHISPER_TIMEOUT


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _mock_ffmpeg():
    """ffmpeg is a prerequisite; mock it as present for all tests."""
    with patch("yttranscript.whisper.shutil.which", return_value="/usr/bin/ffmpeg"):
        yield


# --- prerequisites --------------------------------------------------------

def test_returns_false_when_no_ffmpeg(capsys):
    with patch("yttranscript.whisper.shutil.which", return_value=None):
        result = transcribe_with_whisper("url", "title")
    assert result is False
    captured = capsys.readouterr()
    err_output = captured.err or captured.out
    assert "ffmpeg" in err_output
    assert "apt" in err_output
    assert "brew" in err_output
    assert "pacman" in err_output


def test_returns_false_when_whisper_unavailable():
    with patch("yttranscript.whisper.ensure_whisper", return_value=False):
        result = transcribe_with_whisper("url", "title", video_info={"duration": 0, "size": 0, "title": "t"})
    assert result is False


# --- audio download failure -----------------------------------------------

def test_audio_download_failure_returns_false():
    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", return_value=_cp(1, "error")):
        result = transcribe_with_whisper(
            "url", "title", video_info={"duration": 60, "size": 1000000, "title": "T"})
    assert result is False


def test_audio_file_not_found_returns_false(tmp_path):
    """yt-dlp returns 0 but no audio file exists in work_dir."""
    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", return_value=_cp(0, "")):
        result = transcribe_with_whisper(
            "url", "title", video_info={"duration": 60, "size": 0, "title": "T"},
            work_dir=tmp_path)
    assert result is False


# --- successful transcription ---------------------------------------------

def test_successful_transcription(tmp_path):
    """Full pipeline: download audio → whisper → rename VTT → success."""
    video_info = {"duration": 120, "size": 5000000, "title": "My Video"}

    def fake_run(cmd, **kwargs):
        # yt-dlp audio download: create the audio file
        if "yt-dlp" in cmd:
            # Find the output template to determine filename
            idx = cmd.index("--output") if "--output" in cmd else cmd.index("-o")
            template = cmd[idx + 1]
            audio_path = template.replace("%(ext)s", "mp3")
            Path(audio_path).write_text("audio")
            return _cp(0)
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        # Whisper creates a VTT file named after the audio (stem + .vtt)
        audio_path = Path(cmd[1])
        vtt_path = audio_path.with_suffix(".vtt")
        vtt_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nTranscribed text\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        result = transcribe_with_whisper(
            "url", "title", model="base", video_info=video_info,
            work_dir=tmp_path)

    assert result is True
    # VTT was renamed to final name
    assert (tmp_path / "title.vtt").exists()
    # Audio was deleted (keep_audio=False)
    assert not (tmp_path / "audio_title.mp3").exists()


def test_keep_audio_preserves_file(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            template = cmd[idx + 1]
            Path(template.replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        result = transcribe_with_whisper(
            "url", "title", video_info=video_info,
            work_dir=tmp_path, keep_audio=True)

    assert result is True
    assert (tmp_path / "audio_title.mp3").exists()


def test_keep_audio_moves_to_keep_dir(tmp_path):
    """When keep_audio_dir is set, audio is moved there."""
    work = tmp_path / "work"; work.mkdir()
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()
    video_info = {"duration": 60, "size": 0, "title": "T"}

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            template = cmd[idx + 1]
            Path(template.replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        result = transcribe_with_whisper(
            "url", "title", video_info=video_info,
            work_dir=work, keep_audio=True, keep_audio_dir=keep_dir)

    assert result is True
    assert (keep_dir / "audio_title.mp3").exists()
    assert not (work / "audio_title.mp3").exists()


# --- GPU → CPU fallback ---------------------------------------------------

def test_gpu_fallback_to_cpu(tmp_path):
    """If GPU whisper fails, it retries on CPU."""
    video_info = {"duration": 60, "size": 0, "title": "T"}
    call_count = {"whisper": 0}

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        call_count["whisper"] += 1
        if call_count["whisper"] == 1:
            return _cp(1)  # GPU fails
        # CPU succeeds
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        result = transcribe_with_whisper(
            "url", "title", device="gpu", video_info=video_info,
            work_dir=tmp_path)

    assert result is True
    assert call_count["whisper"] == 2


def test_both_gpu_and_cpu_fail(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        return _cp(1)  # always fail

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        result = transcribe_with_whisper(
            "url", "title", device="gpu", video_info=video_info,
            work_dir=tmp_path)

    assert result is False


# --- whisper command construction -----------------------------------------

def test_whisper_cmd_includes_language(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        captured_cmd.append(list(cmd))
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        transcribe_with_whisper(
            "url", "title", language="es", model="small",
            video_info=video_info, work_dir=tmp_path)

    cmd = captured_cmd[0]
    assert "--language" in cmd
    assert "es" in cmd
    assert "--model" in cmd
    assert "small" in cmd
    assert "--output_format" in cmd
    assert "vtt" in cmd
    assert "--output_dir" in cmd
    assert str(tmp_path) in cmd


def test_whisper_cmd_download_root(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}
    captured_cmd = []

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        captured_cmd.append(list(cmd))
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        transcribe_with_whisper(
            "url", "title", download_dir="/tmp/models",
            video_info=video_info, work_dir=tmp_path)

    cmd = captured_cmd[0]
    assert "--download_root" in cmd
    assert "/tmp/models" in cmd


def test_cpu_device_sets_cuda_env(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}
    captured_env = []

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        captured_env.append(kwargs.get("env", {}))
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        transcribe_with_whisper(
            "url", "title", device="cpu", video_info=video_info,
            work_dir=tmp_path)

    assert captured_env[0].get("CUDA_VISIBLE_DEVICES") == ""


def test_quiet_suppresses_whisper_output(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}
    captured_kwargs = {}

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        transcribe_with_whisper(
            "url", "title", quiet=True, video_info=video_info,
            work_dir=tmp_path)

    assert captured_kwargs.get("stdout") == subprocess.DEVNULL
    assert captured_kwargs.get("stderr") == subprocess.DEVNULL


# --- timeout passthrough --------------------------------------------------

def test_custom_timeout_passed_to_subprocess(tmp_path):
    video_info = {"duration": 60, "size": 0, "title": "T"}
    captured_kwargs = {}

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        transcribe_with_whisper(
            "url", "title", video_info=video_info,
            work_dir=tmp_path, timeout=600)

    assert captured_kwargs.get("timeout") == 600


def test_default_timeout_is_whisper_timeout():
    assert WHISPER_TIMEOUT == 4 * 3600


# --- network options propagation ------------------------------------------

def test_audio_download_forwards_network_to_ytdlp(tmp_path):
    """NetworkOpts are inserted into the yt-dlp audio-download argv."""
    from yttranscript.ytdlp import NetworkOpts
    video_info = {"duration": 60, "size": 0, "title": "T"}
    captured_cmds = []

    def fake_run(cmd, **kwargs):
        if "yt-dlp" in cmd:
            captured_cmds.append(list(cmd))
            idx = cmd.index("--output")
            Path(cmd[idx + 1].replace("%(ext)s", "mp3")).write_text("audio")
        return _cp(0)

    def fake_subprocess_run(cmd, **kwargs):
        Path(cmd[1]).with_suffix(".vtt").write_text("WEBVTT\n")
        return _cp(0)

    with patch("yttranscript.whisper.ensure_whisper", return_value=True), \
         patch("yttranscript.whisper.run", side_effect=fake_run), \
         patch("yttranscript.whisper.subprocess.run", side_effect=fake_subprocess_run):
        transcribe_with_whisper(
            "url", "title", video_info=video_info, work_dir=tmp_path,
            network=NetworkOpts(proxy="socks5://h:1080", force_ipv4=True),
        )

    ytdlp_cmds = [c for c in captured_cmds if "yt-dlp" in c]
    assert len(ytdlp_cmds) == 1
    cmd = ytdlp_cmds[0]
    assert "--proxy" in cmd and "socks5://h:1080" in cmd
    assert "--force-ipv4" in cmd
    assert cmd[-1] == "url"  # URL stays last


def test_whisper_fetches_info_with_network_when_video_info_missing(tmp_path):
    """When video_info is None, get_video_info() must receive the same NetworkOpts."""
    from yttranscript.ytdlp import NetworkOpts

    with patch("yttranscript.whisper.ensure_whisper", return_value=False), \
         patch("yttranscript.whisper.get_video_info") as m_info:
        m_info.return_value = {"duration": 0, "size": 0, "title": "T",
                               "channel": "", "upload_date": ""}
        transcribe_with_whisper(
            "url", "title",
            network=NetworkOpts(proxy="socks5://x"),
        )
    m_info.assert_called_once()
    assert m_info.call_args.kwargs.get("network") is not None
    assert m_info.call_args.kwargs["network"].proxy == "socks5://x"
