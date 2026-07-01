"""Tests for yttranscript.cli: argument parsing and main entry point."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from yttranscript.cli import build_parser, main, show_config
from yttranscript._version import __version__
from yttranscript.ytdlp import NetworkOpts


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
        "--summarize-backend", "api",
        "--summarize-api-url", "https://api.openai.com/v1/chat/completions",
        "--summarize-api-model", "gpt-4o-mini",
        "--summarize-api-key-env", "MY_KEY",
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
    assert args.summarize_backend == "api"
    assert args.summarize_api_url == "https://api.openai.com/v1/chat/completions"
    assert args.summarize_api_model == "gpt-4o-mini"
    assert args.summarize_api_key_env == "MY_KEY"
    assert args.list_subs is True
    assert args.output == "mytitle"
    assert args.quiet is True
    assert args.work_dir == "/tmp/work"
    assert args.output_dir == "/tmp/out"


def test_parser_verbose():
    parser = build_parser()
    args = parser.parse_args(["-v", "URL"])
    assert args.verbose is True


def test_parser_summarize_backend_choices():
    parser = build_parser()
    # invalid backend rejected
    with pytest.raises(SystemExit):
        parser.parse_args(["URL", "--summarize-backend", "bogus"])
    args = parser.parse_args(["URL", "--summarize-backend", "api"])
    assert args.summarize_backend == "api"


# --- _resolve_options: summarize backend + API key -----------------------

def test_resolve_options_reads_api_key_from_env(monkeypatch):
    from yttranscript.cli import _resolve_options
    parser = build_parser()
    args = parser.parse_args([
        "URL", "--summarize-backend", "api",
        "--summarize-api-key-env", "MY_TEST_KEY",
    ])
    monkeypatch.setenv("MY_TEST_KEY", "secret-123")
    opts = _resolve_options(args, config={})
    assert opts["summarize_backend"] == "api"
    assert opts["summarize_api_key"] == "secret-123"
    # URL/model fall back to defaults (None) when unset
    assert opts["summarize_api_url"] is None


def test_resolve_options_missing_env_key_yields_none(monkeypatch):
    from yttranscript.cli import _resolve_options
    parser = build_parser()
    args = parser.parse_args(["URL"])
    monkeypatch.delenv("YTTRANSCRIPT_API_KEY", raising=False)
    opts = _resolve_options(args, config={})
    assert opts["summarize_backend"] == "cmd"
    assert opts["summarize_api_key"] is None


def test_resolve_options_backend_from_config(monkeypatch):
    from yttranscript.cli import _resolve_options
    parser = build_parser()
    args = parser.parse_args(["URL"])  # no --summarize-backend
    monkeypatch.setenv("YTTRANSCRIPT_API_KEY", "k")
    opts = _resolve_options(args, config={
        "summarize_backend": "api",
        "summarize_api_url": "https://x/v1/chat/completions",
        "summarize_api_model": "gpt-4o-mini",
    })
    assert opts["summarize_backend"] == "api"
    assert opts["summarize_api_url"] == "https://x/v1/chat/completions"
    assert opts["summarize_api_model"] == "gpt-4o-mini"
    assert opts["summarize_api_key"] == "k"


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


def test_parser_format_epub():
    parser = build_parser()
    args = parser.parse_args(["URL", "-f", "epub"])
    assert args.format == "epub"


def test_parser_format_docx():
    parser = build_parser()
    args = parser.parse_args(["URL", "-f", "docx"])
    assert args.format == "docx"


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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/@chan", "--latest", "5"])
    main()
    mock_list.assert_called_once()
    args, kwargs = mock_list.call_args
    assert args[:2] == ("https://youtube.com/@chan", 5)
    assert isinstance(kwargs.get("network"), NetworkOpts)


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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("sys.argv", ["yttranscript", "https://youtube.com/@chan", "--latest", "3"])
    main()
    mock_list.assert_called_once()
    mock_pv.assert_not_called()


def test_main_latest_transcribe_processes_all(monkeypatch):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
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
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
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


# --- --merge flag ---------------------------------------------------------

def test_parser_merge_flag():
    parser = build_parser()
    args = parser.parse_args(["URL", "--merge"])
    assert args.merge is True


def test_merge_requires_transcribe(monkeypatch):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "URL", "--merge",
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_merge_rejects_txt_format(monkeypatch):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", MagicMock())
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "3", "--transcribe", "--summarize", "--merge",
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_merge_rejects_json_format(monkeypatch):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", MagicMock())
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "3", "--transcribe", "--summarize", "--merge", "-f", "json",
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_merge_accepts_epub_format(monkeypatch):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "3", "--transcribe", "--summarize", "--merge", "-f", "epub",
    ])
    main()
    mock_merge.assert_called_once()
    assert mock_merge.call_args.kwargs["fmt"] == "epub"


def test_merge_accepts_docx_format(monkeypatch):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "3", "--transcribe", "--summarize", "--merge", "-f", "docx",
    ])
    main()
    mock_merge.assert_called_once()
    assert mock_merge.call_args.kwargs["fmt"] == "docx"


def test_merge_accepts_pdf_format(monkeypatch):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "3", "--transcribe", "--summarize", "--merge", "-f", "pdf",
    ])
    main()
    mock_merge.assert_called_once()
    assert mock_merge.call_args.kwargs["fmt"] == "pdf"


def test_merge_naming_with_output(monkeypatch, tmp_path):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS[:1]))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "1", "--transcribe", "--summarize", "--merge", "-f", "epub",
        "--output", "myseries",
    ])
    main()
    merge_path = mock_merge.call_args.args[1]
    assert merge_path.name == "myseries_merged.epub"


def test_merge_naming_without_output(monkeypatch, tmp_path):
    mock_list = MagicMock(return_value=("MyChannel", VIDEOS[:1]))
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/@chan",
        "--latest", "1", "--transcribe", "--summarize", "--merge", "-f", "docx",
    ])
    main()
    merge_path = mock_merge.call_args.args[1]
    assert merge_path.name == "MyChannel.docx"


# --- --group flag -----------------------------------------------------------

def test_parser_group_flag():
    parser = build_parser()
    args = parser.parse_args(["--group", "tech", "--transcribe"])
    assert args.group == "tech"


def test_group_requires_transcribe(monkeypatch):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("sys.argv", ["yttranscript", "--group", "tech"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_group_no_url_required(monkeypatch):
    mock_list = MagicMock(return_value=("Channel", []))
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {
        "channels": {"tech": ["https://www.youtube.com/@Fireship"]},
    })
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "--group", "tech", "--transcribe",
    ])
    main()
    mock_list.assert_called_once()


def test_main_group_merge_creates_single_file(monkeypatch):
    mock_list = MagicMock(side_effect=[
        ("Channel1", [("2024-01-15", "vid1", "Video 1"), ("2024-01-14", "vid2", "Video 2")]),
        ("Channel2", [("2024-01-13", "vid3", "Video 3")]),
    ])
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {
        "channels": {"tech": ["https://youtube.com/@ch1", "https://youtube.com/@ch2"]},
    })
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "--group", "tech", "--transcribe",
        "--summarize", "--merge", "-f", "epub",
    ])
    main()
    mock_merge.assert_called_once()
    sections = mock_merge.call_args.args[0]
    assert len(sections) == 3
    merge_path = mock_merge.call_args.args[1]
    assert merge_path.name == "tech.epub"
    assert mock_merge.call_args.kwargs["channel_name"] == "tech"


def test_main_group_merge_with_output_flag(monkeypatch):
    mock_list = MagicMock(side_effect=[
        ("Channel1", [("2024-01-15", "vid1", "Video 1")]),
    ])
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {
        "channels": {"tech": ["https://youtube.com/@ch1"]},
    })
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "--group", "tech", "--transcribe",
        "--summarize", "--merge", "-f", "epub", "-o", "mynews",
    ])
    main()
    merge_path = mock_merge.call_args.args[1]
    assert merge_path.name == "mynews_merged.epub"


def test_main_group_no_merge_without_flag(monkeypatch):
    mock_list = MagicMock(side_effect=[
        ("Channel1", [("2024-01-15", "vid1", "Video 1")]),
    ])
    mock_pv = MagicMock(return_value=("title", "summary text"))
    mock_merge = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.list_channel_videos", mock_list)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {
        "channels": {"tech": ["https://youtube.com/@ch1"]},
    })
    monkeypatch.setattr("yttranscript.cli.markdown_to_merged", mock_merge)
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "--group", "tech", "--transcribe",
        "--summarize", "-f", "epub",
    ])
    main()
    mock_merge.assert_not_called()


# --- __main__.py exit code propagation -------------------------------------

def test_main_module_propagates_exit_code_2(monkeypatch):
    """python -m yttranscript with no args should exit 2."""
    result = subprocess.run(
        ["python", "-m", "yttranscript"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_main_module_propagates_exit_code_0(monkeypatch):
    """python -m yttranscript --version should exit 0."""
    result = subprocess.run(
        ["python", "-m", "yttranscript", "--version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout


# --- _resolve_options ------------------------------------------------------

def test_resolve_options_returns_dict():
    from yttranscript.cli import _resolve_options
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x"])
    opts = _resolve_options(args, {})
    assert isinstance(opts, dict)
    assert opts["fmt"] == "txt"
    assert opts["lang"] is None
    assert opts["use_cache"] is True
    assert opts["skip_cached"] is False


def test_resolve_options_respects_no_cache():
    from yttranscript.cli import _resolve_options
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x", "--no-cache"])
    opts = _resolve_options(args, {})
    assert opts["use_cache"] is False
    assert opts["skip_cached"] is False


def test_resolve_options_skip_cached():
    from yttranscript.cli import _resolve_options
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x", "--skip-cached"])
    opts = _resolve_options(args, {})
    assert opts["use_cache"] is True
    assert opts["skip_cached"] is True


# --- --summarize-api-list-models -----------------------------------------

def test_parser_list_models_flag():
    parser = build_parser()
    args = parser.parse_args(["--summarize-api-list-models"])
    assert args.summarize_api_list_models is True
    # Works without a positional URL
    assert args.url is None


def test_list_models_no_url_configured_exits_1(monkeypatch, capsys):
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", ["yttranscript", "--summarize-api-list-models"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "summarize_api_url" in err.lower()


def test_list_models_no_api_key_exits_1(monkeypatch, capsys):
    config = {"summarize_api_url": "https://api.openai.com/v1/chat/completions"}
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: config)
    monkeypatch.delenv("YTTRANSCRIPT_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["yttranscript", "--summarize-api-list-models"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "YTTRANSCRIPT_API_KEY" in err


def test_list_models_success_prints_table_and_exits_0(monkeypatch, capsys):
    config = {"summarize_api_url": "https://api.openai.com/v1/chat/completions"}
    fake_models = [
        {"id": "gpt-4o", "owned_by": "openai", "created": 1715367600},
        {"id": "gpt-4o-mini", "owned_by": "openai", "created": 1721260800},
    ]
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: config)
    monkeypatch.setattr("yttranscript.cli.os.environ.get", lambda k: "k" if k == "YTTRANSCRIPT_API_KEY" else None)
    monkeypatch.setattr("yttranscript.summarize.list_models", lambda url, key, timeout=300: fake_models)
    monkeypatch.setattr("sys.argv", ["yttranscript", "--summarize-api-list-models"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Endpoint:" in out
    assert "https://api.openai.com/v1/chat/completions" in out
    assert "gpt-4o" in out
    assert "gpt-4o-mini" in out
    assert "2 model(s)" in out


def test_list_models_api_failure_exits_1(monkeypatch, capsys):
    config = {"summarize_api_url": "https://api.openai.com/v1/chat/completions"}
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: config)
    monkeypatch.setattr("yttranscript.cli.os.environ.get", lambda k: "k" if k == "YTTRANSCRIPT_API_KEY" else None)
    monkeypatch.setattr("yttranscript.summarize.list_models", lambda url, key, timeout=300: None)
    monkeypatch.setattr("sys.argv", ["yttranscript", "--summarize-api-list-models"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_print_models_table_empty_warns(capsys):
    from yttranscript.cli import _print_models_table
    _print_models_table([])
    out = capsys.readouterr().out
    assert "No models" in out


def test_print_models_table_missing_created_shows_question(capsys):
    from yttranscript.cli import _print_models_table
    _print_models_table([{"id": "weird", "owned_by": "?", "created": None}])
    out = capsys.readouterr().out
    assert "weird" in out
    assert "?" in out


# --- network / anti-block options (_resolve_network_opts) ------------------

def _parse_cli_network(argv_extra):
    """Build parser, parse argv, return resolved NetworkOpts."""
    from yttranscript.cli import _resolve_network_opts, build_parser
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x", *argv_extra])
    return _resolve_network_opts(args, {})


def test_resolve_network_proxy_from_cli():
    opts = _parse_cli_network(["--proxy", "socks5://127.0.0.1:1080"])
    assert opts.proxy == "socks5://127.0.0.1:1080"
    assert opts.is_empty() is False


def test_resolve_network_cookies_and_browser_from_cli():
    opts = _parse_cli_network(["--cookies", "/tmp/c.txt", "--cookies-from-browser", "firefox"])
    assert opts.cookies == "/tmp/c.txt"
    assert opts.cookies_from_browser == "firefox"


def test_resolve_network_force_ipv4_and_geo_bypass_from_cli():
    opts = _parse_cli_network(["--force-ipv4", "--geo-bypass"])
    assert opts.force_ipv4 is True
    assert opts.geo_bypass is True


def test_resolve_network_extractor_args_from_cli():
    opts = _parse_cli_network(["--extractor-args", "youtube:player_client=-android"])
    assert opts.extractor_args == "youtube:player_client=-android"


def test_resolve_network_ytdlp_args_cli_string_is_shlex_split():
    opts = _parse_cli_network(["--ytdlp-args", "--retries 10 --sleep-requests 1"])
    assert opts.extra_args == ["--retries", "10", "--sleep-requests", "1"]


def test_resolve_network_ytdlp_args_preserves_quoted_values():
    opts = _parse_cli_network(["--ytdlp-args", '--user-agent "Mozilla/5.0"'])
    assert opts.extra_args == ["--user-agent", "Mozilla/5.0"]


def test_resolve_network_cli_overrides_config():
    """CLI value wins over config value for the same key."""
    from yttranscript.cli import _resolve_network_opts, build_parser
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x", "--proxy", "http://cli"])
    config = {"proxy": "http://config"}
    opts = _resolve_network_opts(args, config)
    assert opts.proxy == "http://cli"


def test_resolve_network_falls_back_to_config():
    """Config values are used when the CLI flag is absent."""
    from yttranscript.cli import _resolve_network_opts, build_parser
    parser = build_parser()
    args = parser.parse_args(["https://youtube.com/watch?v=x"])
    config = {
        "proxy": "http://config",
        "force_ipv4": True,
        "ytdlp_args": ["--retries", "5"],
    }
    opts = _resolve_network_opts(args, config)
    assert opts.proxy == "http://config"
    assert opts.force_ipv4 is True
    assert opts.extra_args == ["--retries", "5"]


def test_resolve_network_defaults_to_empty():
    """No CLI, no config → all defaults, is_empty() True."""
    opts = _parse_cli_network([])
    assert opts.proxy is None
    assert opts.force_ipv4 is False
    assert opts.extra_args == []
    assert opts.is_empty() is True


def test_process_video_receives_network_opts_from_cli(monkeypatch):
    """End-to-end: --proxy on the CLI reaches process_video().network."""
    mock_pv = MagicMock()
    monkeypatch.setattr("yttranscript.cli.ensure_config_dir", lambda: None)
    monkeypatch.setattr("yttranscript.cli.process_video", mock_pv)
    monkeypatch.setattr("yttranscript.cli.load_config", lambda: {})
    monkeypatch.setattr("sys.argv", [
        "yttranscript", "https://youtube.com/watch?v=x",
        "--proxy", "socks5://127.0.0.1:1080",
    ])
    main()
    mock_pv.assert_called_once()
    net = mock_pv.call_args.kwargs.get("network")
    assert isinstance(net, NetworkOpts)
    assert net.proxy == "socks5://127.0.0.1:1080"
    assert "--proxy" in net.to_ytdlp_args()
