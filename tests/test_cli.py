"""Tests for yttranscript.cli: argument parsing and main entry point."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from yttranscript.cli import build_parser, main, show_config
from yttranscript._version import __version__


# --- build_parser ---------------------------------------------------------

def test_parser_has_url_positional():
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x"])
    assert args.url == "https://youtube.com/watch?v=x"


def test_parser_url_optional():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.url is None


def test_parser_all_flags():
    parser = build_parser()
    args = parser.parse_args([
        "https://youtube.com/watch?v=x",
        "--lang", "es",
        "--format", "json",
        "--chunk-size", "60",
        "--timestamps",
        "--whisper",
        "--whisper-model", "small",
        "--whisper-dir", "/tmp/models",
        "--whisper-device", "cpu",
        "--keep-vtt",
        "--keep-audio",
        "--stdout",
        "--summarize",
        "--summarize-cmd", "llama-cli",
        "--summarize-prompt", "Summarize",
        "--list-subs",
        "--output", "mytitle",
        "--quiet",
        "--work-dir", "/tmp/work",
        "--output-dir", "/tmp/out",
    ])
    assert args.lang == "es"
    assert args.format == "json"
    assert args.chunk_size == 60
    assert args.timestamps is True
    assert args.whisper is True
    assert args.whisper_model == "small"
    assert args.whisper_dir == "/tmp/models"
    assert args.whisper_device == "cpu"
    assert args.keep_vtt is True
    assert args.keep_audio is True
    assert args.stdout is True
    assert args.summarize is True
    assert args.summarize_cmd == "llama-cli"
    assert args.summarize_prompt == "Summarize"
    assert args.list_subs is True
    assert args.output == "mytitle"
    assert args.quiet is True
    assert args.work_dir == "/tmp/work"
    assert args.output_dir == "/tmp/out"


def test_parser_verbose():
    parser = build_parser()
    args = parser.parse_args(["-v", "URL"])
    assert args.verbose is True


def test_parser_serve_and_port():
    parser = build_parser()
    args = parser.parse_args(["--serve", "--port", "9999"])
    assert args.serve is True
    assert args.port == 9999


def test_parser_latest_default_const():
    parser = build_parser()
    args = parser.parse_args(["URL", "--latest"])
    assert args.latest == 10


def test_parser_latest_explicit():
    parser = build_parser()
    args = parser.parse_args(["URL", "--latest", "5"])
    assert args.latest == 5


def test_parser_format_choices():
    parser = build_parser()
    args = parser.parse_args(["URL", "-f", "vtt"])
    assert args.format == "vtt"


def test_parser_format_invalid_choice_exits():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["URL", "-f", "xml"])


def test_parser_version(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_parser_whisper_model_choices():
    parser = build_parser()
    for m in ("tiny", "base", "small", "medium", "large"):
        args = parser.parse_args(["URL", "--whisper-model", m])
        assert args.whisper_model == m


# --- show_config ----------------------------------------------------------

def test_show_config_exits_zero(capsys, monkeypatch):
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    with pytest.raises(SystemExit) as exc:
        show_config()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Config file:" in captured.out
    assert "lang" in captured.out


def test_show_config_shows_resolved_values(capsys, monkeypatch):
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {"lang": "es"})
    with pytest.raises(SystemExit):
        show_config()
    captured = capsys.readouterr()
    assert "es" in captured.out
    assert "config" in captured.out


def test_show_config_hides_hidden_keys(capsys, monkeypatch):
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    with pytest.raises(SystemExit):
        show_config()
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    for line in lines:
        assert not line.strip().startswith("output:")
        assert not line.strip().startswith("port:")


# --- main: argument handling ----------------------------------------------

def test_main_no_url_errors(monkeypatch):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("sys.argv", ["yttranscript"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_main_invalid_url_errors(monkeypatch):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://example.com/"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_main_quiet_sets_verbosity(monkeypatch):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", MagicMock())
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "-q", "https://youtube.com/watch?v=x"])
    from yttranscript import log
    old = log.VERBOSITY
    try:
        main()
        assert log.VERBOSITY == 0
    finally:
        log.VERBOSITY = old


def test_main_verbose_sets_verbosity(monkeypatch):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", MagicMock())
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "-v", "https://youtube.com/watch?v=x"])
    from yttranscript import log
    old = log.VERBOSITY
    try:
        main()
        assert log.VERBOSITY == 2
    finally:
        log.VERBOSITY = old


# --- main: dispatch to serve / list / process -----------------------------

def test_main_serve_calls_run_server(monkeypatch):
    mock_serve = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.run_server", mock_serve)
    monkeypatch.setattr("sys.argv", ["yttranscript", "--serve", "--port", "9999"])
    main()
    mock_serve.assert_called_once_with(9999)


def test_main_latest_calls_list_channel_videos(monkeypatch):
    mock_list = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/@chan", "--latest", "5"])
    main()
    mock_list.assert_called_once_with("https://youtube.com/@chan", 5)


def test_main_calls_process_video_with_resolved_values(monkeypatch):
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {"lang": "es", "format": "json"})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/watch?v=x",
        "--output", "myvid",
        "--chunk-size", "60",
    ])
    main()
    mock_pv.assert_called_once()
    call_kwargs = mock_pv.call_args.kwargs
    assert call_kwargs["url"] == "https://youtube.com/watch?v=x"
    assert call_kwargs["output"] == "myvid"
    assert call_kwargs["lang"] == "es"
    assert call_kwargs["fmt"] == "json"
    assert call_kwargs["chunk_size"] == 60


# --- main: error handling -------------------------------------------------

def test_main_keyboard_interrupt_exits_130(monkeypatch):
    mock_pv = MagicMock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/watch?v=x"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 130


def test_main_timeout_expired_exits_1(monkeypatch, capsys):
    err = subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=60)
    mock_pv = MagicMock(side_effect=err)
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/watch?v=x"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    output = captured.err or captured.out
    assert "timed out" in output.lower()
    assert "TimeoutExpired" not in output


def test_main_called_process_error_exits_1(monkeypatch, capsys):
    err = subprocess.CalledProcessError(returncode=1, cmd=["yt-dlp"])
    mock_pv = MagicMock(side_effect=err)
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/watch?v=x"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    output = captured.err or captured.out
    assert "CalledProcessError" not in output
    assert "--verbose" in output


def test_main_generic_exception_no_type_name(monkeypatch, capsys):
    mock_pv = MagicMock(side_effect=ValueError("something went wrong"))
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/watch?v=x"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    combined = captured.err + captured.out
    assert "ValueError" not in combined
    assert "something went wrong" in combined
    assert "--verbose" in combined


def test_main_transcript_error_exits_1(monkeypatch):
    from yttranscript.util import TranscriptError
    mock_pv = MagicMock(side_effect=TranscriptError("bad video"))
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/watch?v=x"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


# --- _validate_args -------------------------------------------------------

def test_validate_rejects_bad_port(monkeypatch):
    monkeypatch.setattr("sys.argv", ["yttranscript", "--serve", "--port", "0"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_validate_rejects_negative_chunk_size(monkeypatch):
    monkeypatch.setattr("sys.argv", ["yttranscript", "URL", "--chunk-size", "-5"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_validate_rejects_zero_latest(monkeypatch):
    monkeypatch.setattr("sys.argv", ["yttranscript", "URL", "--latest", "0"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_validate_rejects_bad_lang(monkeypatch):
    monkeypatch.setattr("sys.argv", ["yttranscript", "URL", "--lang", "español"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


# --- ensure_config_dir timing ---------------------------------------------

def test_config_dir_not_created_for_version(monkeypatch):
    """--version must not create ~/.config/yttranscript/."""
    mock_ensure = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", mock_ensure)
    monkeypatch.setattr("sys.argv", ["yttranscript", "--version"])
    with pytest.raises(SystemExit):
        main()
    mock_ensure.assert_not_called()


# --- --latest --transcribe (batch mode) ------------------------------------

VIDEOS = [
    ("2024-01-15", "vid1", "First Video"),
    ("2024-01-14", "vid2", "Second Video"),
    ("2024-01-13", "vid3", "Third Video"),
]


def test_main_latest_without_transcribe_lists_only(monkeypatch):
    mock_list = MagicMock(return_value=VIDEOS)
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/@chan", "--latest", "3"])
    main()
    mock_list.assert_called_once()
    mock_pv.assert_not_called()


def test_main_latest_transcribe_processes_all(monkeypatch):
    mock_list = MagicMock(return_value=VIDEOS)
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan", "--latest", "3", "--transcribe",
    ])
    main()
    assert mock_pv.call_count == 3
    urls = [c.kwargs["url"] for c in mock_pv.call_args_list]
    assert urls == [
        "https://www.youtube.com/watch?v=vid1",
        "https://www.youtube.com/watch?v=vid2",
        "https://www.youtube.com/watch?v=vid3",
    ]


def test_main_batch_continues_on_error(monkeypatch):
    from yttranscript.util import TranscriptError
    mock_list = MagicMock(return_value=VIDEOS)
    mock_pv = MagicMock(side_effect=[TranscriptError("fail"), None, None])
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan", "--latest", "3", "--transcribe",
    ])
    main()
    assert mock_pv.call_count == 3


def test_main_batch_stdout_allowed(monkeypatch):
    mock_list = MagicMock(return_value=VIDEOS)
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan", "--latest", "3",
        "--transcribe", "--stdout",
    ])
    main()
    assert mock_pv.call_count == 3
    assert all(c.kwargs["stdout_mode"] is True for c in mock_pv.call_args_list)


def test_main_batch_output_as_prefix(monkeypatch):
    mock_list = MagicMock(return_value=VIDEOS)
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan", "--latest", "3",
        "--transcribe", "--output", "name",
    ])
    main()
    assert mock_pv.call_count == 3
    outputs = [c.kwargs["output"] for c in mock_pv.call_args_list]
    assert outputs == ["name_First Video", "name_Second Video", "name_Third Video"]


def test_main_batch_list_subs_rejected(monkeypatch):
    mock_list = MagicMock(return_value=VIDEOS)
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan", "--latest", "3",
        "--transcribe", "--list-subs",
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_main_transcribe_without_latest_ignored(monkeypatch):
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/watch?v=x", "--transcribe",
    ])
    main()
    mock_pv.assert_called_once()
    assert mock_pv.call_args.kwargs["url"] == "https://youtube.com/watch?v=x"
    assert mock_pv.call_args.kwargs["summarize"] is False


def test_main_batch_keyboard_interrupt_breaks(monkeypatch):
    mock_list = MagicMock(return_value=VIDEOS)
    mock_pv = MagicMock(side_effect=[None, KeyboardInterrupt(), None])
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan", "--latest", "3", "--transcribe",
    ])
    main()
    assert mock_pv.call_count == 2
