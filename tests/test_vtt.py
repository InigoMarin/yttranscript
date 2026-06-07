"""Tests for yttranscript.vtt: parsing, conversion, headers."""

from __future__ import annotations

import json

import pytest

from yttranscript import vtt


# --- timestamp helpers ----------------------------------------------------

@pytest.mark.parametrize("time_str, expected", [
    ("00:00:00.000", 0),
    ("00:01:23.000", 83),
    ("01:02:03.500", 3723),
    ("02:30", 150),
    ("bogus", 0),
    ("", 0),
])
def test_vtt_time_to_seconds(time_str, expected):
    assert vtt._vtt_time_to_seconds(time_str) == expected


@pytest.mark.parametrize("total, expected", [
    (0, "00:00"),
    (59, "00:59"),
    (60, "01:00"),
    (3599, "59:59"),
    (3600, "01:00:00"),
    (3661, "01:01:01"),
])
def test_seconds_to_ts(total, expected):
    assert vtt._seconds_to_ts(total) == expected


# --- parse_vtt ------------------------------------------------------------

def test_parse_yields_cues_in_order(sample_vtt_path):
    cues = list(vtt.parse_vtt(sample_vtt_path))
    assert [s for s, _ in cues] == [0, 2, 5, 7]


def test_parse_strips_html_tags_and_entities(sample_vtt_path):
    cues = list(vtt.parse_vtt(sample_vtt_path))
    assert cues[1][1] == ["This is a test & demo"]
    assert cues[3][1] == ["Final line 'with quotes'"]


def test_parse_skips_header_lines(tmp_path):
    """WEBVTT / Kind: / Language: header lines don't become cues."""
    p = tmp_path / "x.vtt"
    p.write_text(
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "Body line\n",
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    assert len(cues) == 1
    assert cues[0][1] == ["Body line"]


def test_parse_handles_multiline_cues(tmp_path):
    p = tmp_path / "x.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:03.000\n"
        "First line of cue\n"
        "Second line of same cue\n"
        "\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "Single line\n",
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    assert cues[0][1] == ["First line of cue", "Second line of same cue"]
    assert cues[1][1] == ["Single line"]


def test_parse_handles_nested_tags(tmp_path):
    """Complex YouTube auto-sub tags like <c.colorXXX>...</c>."""
    p = tmp_path / "x.vtt"
    p.write_text(
        'WEBVTT\n\n'
        '00:00:00.000 --> 00:00:02.000\n'
        '<c.colorE5E5E5>complex <b>tag</b></c>\n',
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    assert cues[0][1] == ["complex tag"]


def test_parse_decodes_entities(tmp_path):
    p = tmp_path / "x.vtt"
    p.write_text(
        'WEBVTT\n\n'
        '00:00:00.000 --> 00:00:02.000\n'
        'Line with &lt;literal&gt; &amp; &quot;quotes&quot;\n',
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    assert cues[0][1] == ['Line with <literal> & "quotes"']


def test_parse_skips_cue_identifiers(tmp_path):
    """Numeric cue identifiers (between timestamp and content) are skipped."""
    p = tmp_path / "x.vtt"
    p.write_text(
        "WEBVTT\n\n"
        "1\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "Body\n",
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    assert cues == [(0, ["Body"])]


def test_parse_empty_file_yields_nothing(tmp_path):
    p = tmp_path / "empty.vtt"
    p.write_text("WEBVTT\n", encoding="utf-8")
    assert list(vtt.parse_vtt(p)) == []


def test_parse_preserves_numeric_content(tmp_path):
    """Subtitle lines that are just numbers ('911', '42') are NOT dropped."""
    p = tmp_path / "x.vtt"
    p.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "911\n\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "42 is the answer\n",
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    assert cues[0][1] == ["911"]
    assert cues[1][1] == ["42 is the answer"]


def test_parse_strips_blank_only_lines(tmp_path):
    """Cue blocks containing only whitespace/empty after cleaning are skipped."""
    p = tmp_path / "x.vtt"
    p.write_text(
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\n"
        "   \n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Real content\n",
        encoding="utf-8",
    )
    cues = list(vtt.parse_vtt(p))
    # Only the second cue has actual content
    assert cues == [(1, ["Real content"])]


# --- plain text conversion ------------------------------------------------

def test_vtt_to_plain_dedups_repeated_lines(sample_vtt_path):
    text = vtt._vtt_to_plain(
        sample_vtt_path,
        video_info={"title": "T", "url": "U", "duration": 10},
    )
    assert text.count("Hello world") == 1
    assert "# T" in text
    assert "**URL:** U" in text


def test_vtt_to_plain_with_timestamps(sample_vtt_path):
    text = vtt._vtt_to_plain(sample_vtt_path, timestamps=True)
    assert "[00:00] Hello world" in text
    assert "[00:02] This is a test & demo" in text


def test_vtt_to_plain_without_video_info(sample_vtt_path):
    text = vtt._vtt_to_plain(sample_vtt_path)
    assert not text.startswith("#")


def test_vtt_to_text_writes_file(sample_vtt_path, tmp_path):
    out = tmp_path / "out.txt"
    vtt.vtt_to_text(sample_vtt_path, out, video_info=None)
    assert out.exists()
    assert "Hello world" in out.read_text(encoding="utf-8")


def test_extract_vtt_plain_text(sample_vtt_path):
    text = vtt.extract_vtt_plain_text(sample_vtt_path)
    assert "Hello world" in text
    assert "Final line 'with quotes'" in text
    # Space-joined, deduped
    assert text.count("Hello world") == 1


# --- JSON output ----------------------------------------------------------

def test_vtt_to_json_structure(sample_vtt_path):
    out = vtt.vtt_to_json(
        sample_vtt_path,
        {"title": "T", "url": "U", "duration": 10},
        chunk_size=5,
    )
    data = json.loads(out)
    assert data["title"] == "T"
    assert data["url"] == "U"
    assert data["duration"] == 10
    assert data["source"] == "subtitles"
    assert data["chunk_size"] == 5
    assert isinstance(data["chunks"], list)
    for chunk in data["chunks"]:
        assert {"start", "end", "start_seconds", "end_seconds", "text"} <= set(chunk)


def test_vtt_to_json_whisper_source(sample_vtt_path):
    out = vtt.vtt_to_json(
        sample_vtt_path,
        {"title": "T", "url": "U", "duration": 10, "whisper": True},
        chunk_size=5,
    )
    assert json.loads(out)["source"] == "whisper"


def test_vtt_to_json_preserves_all_cues(sample_vtt_path):
    """JSON output keeps every cue (dedup only applies to plain text)."""
    out = vtt.vtt_to_json(
        sample_vtt_path,
        {"title": "T", "url": "U", "duration": 10},
        chunk_size=100,
    )
    data = json.loads(out)
    all_text = " ".join(c["text"] for c in data["chunks"])
    assert "Hello world" in all_text
    assert "Final line" in all_text


def test_vtt_to_json_handles_empty_vtt(tmp_path):
    p = tmp_path / "empty.vtt"
    p.write_text("WEBVTT\n", encoding="utf-8")
    out = vtt.vtt_to_json(p, {"title": "T", "url": "U", "duration": 0}, chunk_size=30)
    data = json.loads(out)
    assert data["chunks"] == []


# --- format_video_header --------------------------------------------------

@pytest.mark.parametrize("duration, expected_substr", [
    (0, "**Duration:** unknown"),
    (65, "**Duration:** 1:05"),
    (3661, "**Duration:** 1:01:01"),
])
def test_format_video_header_duration(duration, expected_substr):
    h = vtt.format_video_header({"title": "T", "url": "U", "duration": duration, "whisper": False})
    assert expected_substr in h


def test_format_video_header_source_label():
    h_sub = vtt.format_video_header({"title": "T", "url": "U", "duration": 0, "whisper": False})
    h_whisper = vtt.format_video_header({"title": "T", "url": "U", "duration": 0, "whisper": True})
    assert "YouTube subtitles" in h_sub
    assert "Whisper" in h_whisper
