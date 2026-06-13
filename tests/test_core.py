"""Tests for yttranscript.core: pipeline orchestration and output rendering."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from yttranscript.util import TranscriptError
from yttranscript.core import _render_output, process_video


# --- process_video URL validation -----------------------------------------

def test_process_video_rejects_non_youtube_url():
    with pytest.raises(TranscriptError, match="Not a YouTube URL"):
        process_video(url="https://example.com/", output_dir="/tmp")


def test_process_video_rejects_none_url():
    with pytest.raises(TranscriptError):
        process_video(url=None)


def test_process_video_rejects_garbage():
    with pytest.raises(TranscriptError):
        process_video(url="javascript:alert(1)")


# --- _render_output: txt mode ---------------------------------------------

def test_render_txt_writes_to_output_dir(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    vtt = work / "video.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    saved = _render_output(
        vtt_path=vtt,
        video_info={"title": "video", "url": "U", "duration": 2, "whisper": False},
        fmt="txt", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    assert saved == (out_dir / "video.txt", None)
    assert saved[0].exists()
    assert "Hello" in saved[0].read_text()
    assert not vtt.exists(), "source VTT should be consumed"
    assert not (work / "video.txt").exists()


def test_render_txt_with_timestamps(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nFirst\n\n"
        "00:00:02.000 --> 00:00:04.000\nSecond\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 4, "whisper": False},
        fmt="txt", stdout_mode=False, timestamps=True, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    content = saved[0].read_text()
    assert "[00:00]" in content
    assert "[00:02]" in content


def test_render_txt_keep_vtt_preserves_in_output_dir(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    vtt = work / "video.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    _render_output(
        vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": False},
        fmt="txt", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=True, output_dir=out_dir,
    )
    assert (out_dir / "video.txt").exists()
    assert (out_dir / "video.vtt").exists()
    assert not vtt.exists(), "source VTT should have been moved"


# --- _render_output: json mode --------------------------------------------

def test_render_json_writes_to_output_dir(tmp_path):
    import json
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 2, "whisper": False},
        fmt="json", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    assert saved == (out_dir / "v.json", None)
    data = json.loads(saved[0].read_text())
    assert data["title"] == "v"
    assert data["source"] == "subtitles"


def test_render_json_whisper_source(tmp_path):
    import json
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": True},
        fmt="json", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    data = json.loads(saved[0].read_text())
    assert data["source"] == "whisper"


# --- _render_output: vtt mode ---------------------------------------------

def test_render_vtt_moves_to_output_dir(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    vtt = work / "video.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "video", "url": "U", "duration": 0, "whisper": False},
        fmt="vtt", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    assert saved == (out_dir / "video.vtt", None)
    assert saved[0].exists()
    assert not vtt.exists()


def test_render_vtt_same_dir_no_move(tmp_path):
    """If output_dir is the same as vtt's dir, no move needed."""
    out_dir = tmp_path / "out"; out_dir.mkdir()
    vtt = out_dir / "video.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "video", "url": "U", "duration": 0, "whisper": False},
        fmt="vtt", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    assert saved == (vtt, None)  # same path


# --- _render_output: pdf mode --------------------------------------------

def test_render_pdf_creates_valid_pdf(tmp_path):
    """fmt='pdf' produces a valid PDF file in output_dir."""
    import shutil
    pytest.mark.skipif(
        not shutil.which("pandoc") or not shutil.which("typst"),
        reason="pandoc and typst required",
    )
    vtt = tmp_path / "video.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello world\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "video", "url": "U", "duration": 2, "whisper": False},
        fmt="pdf", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    pdf_file = out_dir / "video.pdf"
    assert saved == (pdf_file, None)
    assert pdf_file.exists()
    assert pdf_file.read_bytes()[:5] == b"%PDF-"


# --- _render_output: epub mode -------------------------------------------

@pytest.mark.skipif(
    not __import__("shutil").which("pandoc"),
    reason="pandoc required",
)
def test_render_epub_creates_valid_epub(tmp_path):
    """fmt='epub' produces a valid EPUB file in output_dir."""
    vtt = tmp_path / "video.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello world\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "video", "url": "U", "duration": 2, "whisper": False},
        fmt="epub", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    epub_file = out_dir / "video.epub"
    assert saved == (epub_file, None)
    assert epub_file.exists()
    assert epub_file.read_bytes()[:2] == b"PK"


# --- _render_output: docx mode -------------------------------------------

@pytest.mark.skipif(
    not __import__("shutil").which("pandoc"),
    reason="pandoc required",
)
def test_render_docx_creates_valid_docx(tmp_path):
    """fmt='docx' produces a valid DOCX file in output_dir."""
    vtt = tmp_path / "video.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello world\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    saved = _render_output(
        vtt_path=vtt, video_info={"title": "video", "url": "U", "duration": 2, "whisper": False},
        fmt="docx", stdout_mode=False, timestamps=False, chunk_size=30,
        summarize=False, summarize_cmd=None, summarize_prompt=None,
        summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
    )
    docx_file = out_dir / "video.docx"
    assert saved == (docx_file, None)
    assert docx_file.exists()
    assert docx_file.read_bytes()[:2] == b"PK"


# --- _render_output: stdout mode ------------------------------------------

def test_render_stdout_txt_prints_and_no_file(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        result = _render_output(
            vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": False},
            fmt="txt", stdout_mode=True, timestamps=False, chunk_size=30,
            summarize=False, summarize_cmd=None, summarize_prompt=None,
            summarize_timeout=300, keep_vtt=False, output_dir=out_dir,
        )
    finally:
        captured = sys.stdout.getvalue()
        sys.stdout = old
    assert result == (None, None)
    assert not out_dir.exists()
    assert "Hi" in captured


def test_render_stdout_vtt_prints_raw(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\nRAW CONTENT\n", encoding="utf-8")
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        _render_output(
            vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 0, "whisper": False},
            fmt="vtt", stdout_mode=True, timestamps=False, chunk_size=30,
            summarize=False, summarize_cmd=None, summarize_prompt=None,
            summarize_timeout=300, keep_vtt=False, output_dir=tmp_path,
        )
    finally:
        captured = sys.stdout.getvalue()
        sys.stdout = old
    assert "RAW CONTENT" in captured


def test_render_stdout_json_prints_json(tmp_path):
    import json
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        _render_output(
            vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": False},
            fmt="json", stdout_mode=True, timestamps=False, chunk_size=30,
            summarize=False, summarize_cmd=None, summarize_prompt=None,
            summarize_timeout=300, keep_vtt=False, output_dir=tmp_path,
        )
    finally:
        captured = sys.stdout.getvalue()
        sys.stdout = old
    data = json.loads(captured)
    assert data["title"] == "v"


# --- _render_output: summarize mode ---------------------------------------

def test_render_summarize_without_cmd_exits(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    with pytest.raises(TranscriptError):
        _render_output(
            vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": False},
            fmt="txt", stdout_mode=False, timestamps=False, chunk_size=30,
            summarize=True, summarize_cmd=None, summarize_prompt=None,
            summarize_timeout=300, keep_vtt=False, output_dir=tmp_path,
        )


def test_render_summarize_api_without_url_exits(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    with pytest.raises(TranscriptError):
        _render_output(
            vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": False},
            fmt="txt", stdout_mode=False, timestamps=False, chunk_size=30,
            summarize=True, summarize_cmd=None, summarize_prompt=None,
            summarize_timeout=300, keep_vtt=False, output_dir=tmp_path,
            summarize_backend="api", summarize_api_url=None,
            summarize_api_model="m", summarize_api_key="k",
        )


def test_render_summarize_api_success(tmp_path):
    vtt = tmp_path / "v.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n", encoding="utf-8")
    with patch("yttranscript.core.do_summarize", return_value="**API summary**") as m_sum:
        out, summary = _render_output(
            vtt_path=vtt, video_info={"title": "v", "url": "U", "duration": 1, "whisper": False},
            fmt="txt", stdout_mode=False, timestamps=False, chunk_size=30,
            summarize=True, summarize_cmd=None, summarize_prompt="P",
            summarize_timeout=300, keep_vtt=False, output_dir=tmp_path,
            summarize_backend="api", summarize_api_url="https://x/v1/chat/completions",
            summarize_api_model="gpt-4o-mini", summarize_api_key="k",
        )
    m_sum.assert_called_once()
    assert m_sum.call_args.kwargs["backend"] == "api"
    assert m_sum.call_args.kwargs["api_url"] == "https://x/v1/chat/completions"
    assert summary == "**API summary**"
    assert out is not None and out.read_text(encoding="utf-8").endswith("**API summary**\n")


# ---------------------------------------------------------------------------
# process_video: integration tests (mocked pipeline)
# ---------------------------------------------------------------------------

VTT_URL = "https://youtube.com/watch?v=abc123"
SAMPLE_VTT_CONTENT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello world\n"


def _sub_success_side_effect(work_path, prefix="transcript_temp"):
    """Return a side_effect for try_download_subtitle that creates a VTT file."""
    def side_effect(url, output_prefix, lang, use_auto=False, work_dir=None, **kwargs):
        vtt = Path(work_dir or work_path) / f"{prefix}.{lang}.vtt"
        vtt.write_text(SAMPLE_VTT_CONTENT, encoding="utf-8")
        return True
    return side_effect


@pytest.fixture
def mock_pipeline():
    """Mock all external deps of process_video. Returns a dict of mocks."""
    mocks = {}
    mocks["ensure_yt_dlp"] = patch("yttranscript.core.ensure_yt_dlp")
    mocks["get_metadata"] = patch("yttranscript.core.get_video_metadata")
    mocks["try_sub"] = patch("yttranscript.core.try_download_subtitle")
    mocks["whisper"] = patch("yttranscript.core.transcribe_with_whisper")
    mocks["list_subs"] = patch("yttranscript.core.list_subs")

    started = {k: v.start() for k, v in mocks.items()}
    started["ensure_yt_dlp"].return_value = None
    started["get_metadata"].return_value = {
        "title": "T",
        "sanitized_title": "test_video",
        "duration": 60,
        "size": 1000000,
        "language": "en",
    }
    started["try_sub"].return_value = False
    started["whisper"].return_value = False
    started["list_subs"].return_value = None
    yield started
    for m in mocks.values():
        m.stop()


# --- list_only mode -------------------------------------------------------

def test_process_video_list_only(mock_pipeline):
    result = process_video(VTT_URL, list_only=True, output_dir="/tmp")
    assert result is None
    mock_pipeline["list_subs"].assert_called_once_with(VTT_URL)


# --- subtitle download success --------------------------------------------

def test_process_video_subtitle_success(mock_pipeline, tmp_path):
    """When subtitle download works, renders output and returns title."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    result = process_video(VTT_URL, output_dir=str(out), work_dir=str(work))
    assert result[0] == "test_video" and result[1] is None
    assert (out / "test_video.txt").exists()
    # Whisper was NOT called
    mock_pipeline["whisper"].assert_not_called()


def test_process_video_subtitle_success_explicit_output(mock_pipeline, tmp_path):
    """When output name is given, it's used as the title."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    result = process_video(VTT_URL, output="my_custom_name",
                           output_dir=str(out), work_dir=str(work))
    assert result[0] == "my_custom_name" and result[1] is None
    assert (out / "my_custom_name.txt").exists()


def test_process_video_subtitle_uses_combined_mode(mock_pipeline, tmp_path):
    """Subtitles are downloaded with try_both=True (combined manual+auto in one call)."""
    work = tmp_path / "work"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    result = process_video(VTT_URL, work_dir=str(work), output_dir=str(tmp_path))
    assert result[0] == "test_video" and result[1] is None
    call_kwargs = mock_pipeline["try_sub"].call_args.kwargs
    assert call_kwargs.get("try_both") is True


def test_process_video_subtitle_tries_multiple_variants(mock_pipeline, tmp_path):
    """When first variant fails, next variant is tried."""
    work = tmp_path / "work"
    call_count = {"n": 0}

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] > 1:
            (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
            return True
        return False

    mock_pipeline["try_sub"].side_effect = fake_sub

    result = process_video(VTT_URL, work_dir=str(work), output_dir=str(tmp_path))
    assert result[0] == "test_video" and result[1] is None
    assert call_count["n"] > 1


# --- Whisper fallback -----------------------------------------------------

def test_process_video_whisper_fallback_success(mock_pipeline, tmp_path):
    """When no subtitles, falls back to Whisper successfully."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_whisper(url, title, **kwargs):
        (Path(kwargs.get("work_dir")) / f"{title}.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["whisper"].side_effect = fake_whisper

    result = process_video(VTT_URL, output_dir=str(out), work_dir=str(work))
    assert result[0] == "test_video" and result[1] is None
    assert (out / "test_video.txt").exists()
    mock_pipeline["whisper"].assert_called_once()


def test_process_video_whisper_fallback_failure(mock_pipeline, tmp_path):
    """When both subs and Whisper fail, sys.exit(1)."""
    mock_pipeline["try_sub"].return_value = False
    mock_pipeline["whisper"].return_value = False

    with pytest.raises(TranscriptError, match="Could not get transcript"):
        process_video(VTT_URL, work_dir=str(tmp_path), output_dir=str(tmp_path))


def test_process_video_force_whisper(mock_pipeline, tmp_path):
    """--whisper skips subtitle download entirely."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_whisper(url, title, **kwargs):
        (Path(kwargs.get("work_dir")) / f"{title}.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["whisper"].side_effect = fake_whisper

    result = process_video(VTT_URL, force_whisper=True,
                           output_dir=str(out), work_dir=str(work))
    assert result[0] == "test_video" and result[1] is None
    mock_pipeline["try_sub"].assert_not_called()
    mock_pipeline["whisper"].assert_called_once()


# --- language detection ---------------------------------------------------

def test_process_video_lang_auto_detect(mock_pipeline, tmp_path):
    """When lang=None, language is detected from metadata."""
    mock_pipeline["try_sub"].return_value = False
    mock_pipeline["whisper"].return_value = False

    with pytest.raises(TranscriptError):
        process_video(VTT_URL, lang=None, work_dir=str(tmp_path),
                      output_dir=str(tmp_path))
    mock_pipeline["get_metadata"].assert_called_once()


def test_process_video_lang_detect_fails_uses_fallback(mock_pipeline, tmp_path):
    """When metadata has no language, falls back to fallback_lang."""
    mock_pipeline["get_metadata"].return_value = {
        "title": "T", "sanitized_title": "test_video",
        "duration": 60, "size": 1000000, "language": None,
    }
    mock_pipeline["try_sub"].return_value = False
    mock_pipeline["whisper"].return_value = False

    with pytest.raises(TranscriptError):
        process_video(VTT_URL, lang=None, fallback_lang="fr",
                      work_dir=str(tmp_path), output_dir=str(tmp_path))
    mock_pipeline["get_metadata"].assert_called_once()


def test_process_video_explicit_lang_skips_detect(mock_pipeline, tmp_path):
    """When lang is given, metadata language is ignored."""
    mock_pipeline["try_sub"].return_value = False
    mock_pipeline["whisper"].return_value = False

    with pytest.raises(TranscriptError):
        process_video(VTT_URL, lang="de", work_dir=str(tmp_path),
                      output_dir=str(tmp_path))
    mock_pipeline["get_metadata"].assert_called_once()
    first_lang = mock_pipeline["try_sub"].call_args_list[0].args[2]
    assert "de" in first_lang


# --- output_dir and work_dir ----------------------------------------------

def test_process_video_default_output_dir_is_cwd(mock_pipeline, isolated_cwd):
    """Without output_dir, the file is saved to CWD."""
    work = isolated_cwd / "work"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    result = process_video(VTT_URL, work_dir=str(work))
    assert result[0] == "test_video" and result[1] is None
    assert (isolated_cwd / "test_video.txt").exists()


def test_process_video_temp_work_dir_cleaned_up(mock_pipeline, tmp_path):
    """When work_dir is not given, a tempdir is used and cleaned up."""
    created_dirs = []
    original_tempdir = __import__("tempfile").TemporaryDirectory

    class TrackingTempDir(original_tempdir):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            created_dirs.append(self.name)

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    with patch("yttranscript.core.tempfile.TemporaryDirectory", TrackingTempDir):
        process_video(VTT_URL, output_dir=str(tmp_path))

    # The tempdir was cleaned up
    assert created_dirs
    assert not Path(created_dirs[0]).exists()


# --- format and rendering dispatch ----------------------------------------

def test_process_video_json_format(mock_pipeline, tmp_path):
    """JSON format produces a .json file."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    process_video(VTT_URL, fmt="json", output_dir=str(out), work_dir=str(work))
    assert (out / "test_video.json").exists()


def test_process_video_vtt_format(mock_pipeline, tmp_path):
    """VTT format produces a .vtt file."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    process_video(VTT_URL, fmt="vtt", output_dir=str(out), work_dir=str(work))
    assert (out / "test_video.vtt").exists()


def test_process_video_stdout_mode(mock_pipeline, tmp_path):
    """stdout_mode prints transcript, no file saved."""
    work = tmp_path / "work"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        result = process_video(VTT_URL, stdout_mode=True,
                               work_dir=str(work), output_dir=str(tmp_path))
    finally:
        captured = sys.stdout.getvalue()
        sys.stdout = old

    assert result[0] == "test_video" and result[1] is None
    assert "Hello world" in captured
    assert not (tmp_path / "test_video.txt").exists()


def test_process_video_keep_vtt(mock_pipeline, tmp_path):
    """keep_vtt preserves the VTT alongside the output."""
    work = tmp_path / "work"
    out = tmp_path / "out"

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    process_video(VTT_URL, keep_vtt=True, output_dir=str(out), work_dir=str(work))
    assert (out / "test_video.txt").exists()
    assert (out / "test_video.vtt").exists()


# --- whisper passthrough params -------------------------------------------

def test_process_video_passes_whisper_params(mock_pipeline, tmp_path):
    """Whisper params (model, device, keep_audio) are forwarded correctly."""
    mock_pipeline["try_sub"].return_value = False

    def fake_whisper(url, title, **kwargs):
        (Path(kwargs["work_dir"]) / f"{title}.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["whisper"].side_effect = fake_whisper

    process_video(VTT_URL, force_whisper=True,
                  whisper_model="large", whisper_device="cpu",
                  keep_audio=True, whisper_dir="/tmp/models",
                  work_dir=str(tmp_path), output_dir=str(tmp_path))

    call = mock_pipeline["whisper"].call_args
    assert call.kwargs["model"] == "large"
    assert call.kwargs["device"] == "cpu"
    assert call.kwargs["keep_audio"] is True
    assert call.kwargs["download_dir"] == "/tmp/models"


def test_process_video_passes_video_info_to_whisper(mock_pipeline, tmp_path):
    """video_info from metadata is reused (not fetched twice) when calling Whisper."""
    mock_pipeline["try_sub"].return_value = False
    mock_pipeline["get_metadata"].return_value = {
        "title": "T", "sanitized_title": "test_video",
        "duration": 120, "size": 2000000, "language": "en",
    }

    def fake_whisper(url, title, **kwargs):
        assert kwargs["video_info"]["duration"] == 120
        (Path(kwargs["work_dir"]) / f"{title}.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["whisper"].side_effect = fake_whisper

    process_video(VTT_URL, force_whisper=True,
                  work_dir=str(tmp_path), output_dir=str(tmp_path))
    # get_video_metadata called only once (for both main flow and whisper)
    mock_pipeline["get_metadata"].assert_called_once()


# --- log_callback ---------------------------------------------------------

def test_process_video_log_callback_receives_events(mock_pipeline, tmp_path):
    """When a log_callback is provided, it receives log events."""
    events = []

    def fake_sub(url, prefix, lang, use_auto=False, work_dir=None, **kwargs):
        (Path(work_dir) / "transcript_temp.en.vtt").write_text(SAMPLE_VTT_CONTENT)
        return True

    mock_pipeline["try_sub"].side_effect = fake_sub

    process_video(VTT_URL, log_callback=lambda lvl, msg: events.append((lvl, msg)),
                  work_dir=str(tmp_path), output_dir=str(tmp_path))

    levels = [lvl for lvl, _ in events]
    assert "info" in levels
    assert "success" in levels
