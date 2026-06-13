"""Tests for yttranscript.pdf: markdown to PDF/EPUB/DOCX conversion via Pandoc."""

from __future__ import annotations

import shutil

import pytest

from yttranscript.pdf import markdown_to_pdf, markdown_to_epub, markdown_to_docx, markdown_to_merged, PANDOC_FORMATS


def _has_pandoc():
    return shutil.which("pandoc") is not None


def _has_pandoc_and_typst():
    return _has_pandoc() and shutil.which("typst") is not None


# ---------------------------------------------------------------------------
# Pandoc format set
# ---------------------------------------------------------------------------

def test_pandoc_formats_includes_all():
    assert PANDOC_FORMATS == {"pdf", "epub", "docx"}


# ---------------------------------------------------------------------------
# PDF tests (require pandoc + typst)
# ---------------------------------------------------------------------------

pytestmark_pdf = pytest.mark.skipif(
    not _has_pandoc_and_typst(), reason="pandoc and typst required"
)


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_pdf_creates_valid_file(tmp_path):
    md = "# Title\n\nThis is a **bold** paragraph.\n\n- Item 1\n- Item 2\n"
    out = tmp_path / "output.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_pdf_renders_headers_and_lists(tmp_path):
    md = "# My Header\n\n## Subsection\n\n- First\n- Second\n\nSome `code` here."
    out = tmp_path / "test.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.stat().st_size > 500


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_pdf_empty_markdown(tmp_path):
    out = tmp_path / "empty.pdf"
    markdown_to_pdf("", out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_pdf_handles_special_characters(tmp_path):
    md = "# Título en Español\n\nTexto con ñ, ü, y emojis: 🎉\n\n— em dash —"
    out = tmp_path / "unicode.pdf"
    markdown_to_pdf(md, out)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_pdf_with_video_info(tmp_path):
    md = "Hello world transcript content here."
    out = tmp_path / "meta.pdf"
    video_info = {
        "title": "Test Video",
        "url": "https://youtube.com/watch?v=abc123",
        "duration": 125,
        "whisper": False,
    }
    markdown_to_pdf(md, out, video_info=video_info)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 500


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_pdf_with_video_info_long_duration(tmp_path):
    md = "Content"
    out = tmp_path / "long.pdf"
    video_info = {
        "title": "Long Video",
        "url": "https://youtube.com/watch?v=xyz",
        "duration": 3661,
        "whisper": True,
    }
    markdown_to_pdf(md, out, video_info=video_info)

    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# EPUB tests (require pandoc only)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_epub_creates_valid_file(tmp_path):
    md = "# Title\n\nThis is a **bold** paragraph.\n\n- Item 1\n- Item 2\n"
    out = tmp_path / "output.epub"
    markdown_to_epub(md, out)

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_epub_is_zip_archive(tmp_path):
    """EPUB files are ZIP archives starting with 'PK'."""
    md = "# Test\n\nContent."
    out = tmp_path / "test.epub"
    markdown_to_epub(md, out)

    assert out.exists()
    assert out.read_bytes()[:2] == b"PK"


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_epub_with_video_info(tmp_path):
    md = "Hello world transcript content."
    out = tmp_path / "meta.epub"
    video_info = {
        "title": "Test Video",
        "url": "https://youtube.com/watch?v=abc123",
        "duration": 125,
        "whisper": False,
    }
    markdown_to_epub(md, out, video_info=video_info)

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_epub_handles_special_characters(tmp_path):
    md = "# Título en Español\n\nTexto con ñ, ü, y emojis: 🎉\n"
    out = tmp_path / "unicode.epub"
    markdown_to_epub(md, out)

    assert out.exists()
    assert out.read_bytes()[:2] == b"PK"


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_epub_empty_markdown(tmp_path):
    out = tmp_path / "empty.epub"
    markdown_to_epub("", out)

    assert out.exists()


# ---------------------------------------------------------------------------
# DOCX tests (require pandoc only)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_docx_creates_valid_file(tmp_path):
    md = "# Title\n\nThis is a **bold** paragraph.\n\n- Item 1\n- Item 2\n"
    out = tmp_path / "output.docx"
    markdown_to_docx(md, out)

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_docx_is_zip_archive(tmp_path):
    """DOCX files are ZIP archives (Office Open XML) starting with 'PK'."""
    md = "# Test\n\nContent."
    out = tmp_path / "test.docx"
    markdown_to_docx(md, out)

    assert out.exists()
    assert out.read_bytes()[:2] == b"PK"


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_docx_with_video_info(tmp_path):
    md = "Hello world transcript content."
    out = tmp_path / "meta.docx"
    video_info = {
        "title": "Test Video",
        "url": "https://youtube.com/watch?v=abc123",
        "duration": 125,
        "whisper": True,
    }
    markdown_to_docx(md, out, video_info=video_info)

    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_docx_handles_special_characters(tmp_path):
    md = "# Título en Español\n\nTexto con ñ, ü, y emojis: 🎉\n"
    out = tmp_path / "unicode.docx"
    markdown_to_docx(md, out)

    assert out.exists()
    assert out.read_bytes()[:2] == b"PK"


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_docx_empty_markdown(tmp_path):
    out = tmp_path / "empty.docx"
    markdown_to_docx("", out)

    assert out.exists()


# ---------------------------------------------------------------------------
# Dependency checking
# ---------------------------------------------------------------------------

def test_check_deps_pdf_raises_without_typst(monkeypatch):
    """PDF format requires both pandoc and typst."""
    monkeypatch.setattr("shutil.which", lambda cmd: cmd == "pandoc")
    with pytest.raises(ImportError, match="typst"):
        from yttranscript.pdf import _check_deps
        _check_deps("pdf")


def test_check_deps_epub_needs_only_pandoc(monkeypatch):
    """EPUB format only requires pandoc, not typst."""
    monkeypatch.setattr("shutil.which", lambda cmd: cmd == "pandoc")
    from yttranscript.pdf import _check_deps
    _check_deps("epub")  # should not raise


def test_check_deps_docx_needs_only_pandoc(monkeypatch):
    """DOCX format only requires pandoc, not typst."""
    monkeypatch.setattr("shutil.which", lambda cmd: cmd == "pandoc")
    from yttranscript.pdf import _check_deps
    _check_deps("docx")  # should not raise


def test_check_deps_raises_without_pandoc(monkeypatch):
    """All formats require pandoc."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    for fmt in ("pdf", "epub", "docx"):
        with pytest.raises(ImportError, match="pandoc"):
            from yttranscript.pdf import _check_deps
            _check_deps(fmt)


# ---------------------------------------------------------------------------
# Merged document tests
# ---------------------------------------------------------------------------

SECTIONS = [
    (
        {"title": "Video One", "url": "https://youtube.com/watch?v=1", "duration": 120, "whisper": False},
        "Summary of the first video with **bold** and a list:\n- A\n- B",
    ),
    (
        {"title": "Video Two", "url": "https://youtube.com/watch?v=2", "duration": 3661, "whisper": True},
        "Summary of the second video.",
    ),
]


@pytest.mark.skipif(not _has_pandoc_and_typst(), reason="pandoc and typst required")
def test_merged_pdf_creates_valid_file(tmp_path):
    out = tmp_path / "merged.pdf"
    markdown_to_merged(SECTIONS, out, fmt="pdf", channel_name="TestChannel")
    assert out.exists()
    assert out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 500


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_merged_epub_creates_valid_file(tmp_path):
    out = tmp_path / "merged.epub"
    markdown_to_merged(SECTIONS, out, fmt="epub", channel_name="TestChannel")
    assert out.exists()
    assert out.read_bytes()[:2] == b"PK"


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_merged_docx_creates_valid_file(tmp_path):
    out = tmp_path / "merged.docx"
    markdown_to_merged(SECTIONS, out, fmt="docx", channel_name="TestChannel")
    assert out.exists()
    assert out.read_bytes()[:2] == b"PK"


@pytest.mark.skipif(not _has_pandoc(), reason="pandoc required")
def test_merged_uses_channel_name_in_frontmatter(tmp_path):
    """The channel_name appears as the YAML title in the generated markdown."""
    out = tmp_path / "named.epub"
    markdown_to_merged(SECTIONS, out, fmt="epub", channel_name="MyAwesomeChannel")
    assert out.exists()
    assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Metadata flag tests (mocked subprocess, no pandoc needed)
# ---------------------------------------------------------------------------

def _run_pandoc_spy(monkeypatch, *, need_typst=False):
    """Monkeypatch subprocess.run and return a list collecting the cmd."""
    calls = []

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeResult()

    monkeypatch.setattr("subprocess.run", _fake_run)
    # Make deps check pass (pandoc always, typst only when requested)
    if need_typst:
        monkeypatch.setattr("shutil.which", lambda cmd: cmd in ("pandoc", "typst"))
    else:
        monkeypatch.setattr("shutil.which", lambda cmd: cmd == "pandoc")
    return calls


def test_epub_passes_metadata_flags(monkeypatch, tmp_path):
    """EPUB passes --metadata=title and --metadata=author when video_info given."""
    calls = _run_pandoc_spy(monkeypatch)
    out = tmp_path / "test.epub"
    video_info = {"title": "My Video", "url": "https://example.com", "duration": 60}
    markdown_to_epub("content", out, video_info=video_info)

    assert len(calls) == 1
    cmd = calls[0]
    assert "--metadata=title=My Video" in cmd
    assert "--metadata=author=yttranscript" in cmd


def test_epub_no_metadata_without_video_info(monkeypatch, tmp_path):
    """EPUB omits --metadata flags when no video_info is provided."""
    calls = _run_pandoc_spy(monkeypatch)
    out = tmp_path / "test.epub"
    markdown_to_epub("content", out)

    assert len(calls) == 1
    cmd = calls[0]
    metadata_flags = [a for a in cmd if a.startswith("--metadata=")]
    assert metadata_flags == []


def test_docx_passes_metadata_flags(monkeypatch, tmp_path):
    """DOCX passes --metadata=title and --metadata=author when video_info given."""
    calls = _run_pandoc_spy(monkeypatch)
    out = tmp_path / "test.docx"
    video_info = {"title": "My Video", "url": "https://example.com", "duration": 60}
    markdown_to_docx("content", out, video_info=video_info)

    assert len(calls) == 1
    cmd = calls[0]
    assert "--metadata=title=My Video" in cmd
    assert "--metadata=author=yttranscript" in cmd


def test_merged_epub_passes_metadata_flags(monkeypatch, tmp_path):
    """Merged EPUB passes --metadata with channel name as title."""
    calls = _run_pandoc_spy(monkeypatch)
    out = tmp_path / "merged.epub"
    markdown_to_merged(SECTIONS, out, fmt="epub", channel_name="TestChannel")

    assert len(calls) == 1
    cmd = calls[0]
    assert "--metadata=title=TestChannel" in cmd
    assert "--metadata=author=TestChannel" in cmd


def test_merged_docx_passes_metadata_flags(monkeypatch, tmp_path):
    """Merged DOCX passes --metadata with channel name as title."""
    calls = _run_pandoc_spy(monkeypatch)
    out = tmp_path / "merged.docx"
    markdown_to_merged(SECTIONS, out, fmt="docx", channel_name="TestChannel")

    assert len(calls) == 1
    cmd = calls[0]
    assert "--metadata=title=TestChannel" in cmd
    assert "--metadata=author=TestChannel" in cmd


def test_merged_pdf_no_metadata_flags(monkeypatch, tmp_path):
    """Merged PDF does not pass --metadata flags."""
    calls = _run_pandoc_spy(monkeypatch, need_typst=True)
    out = tmp_path / "merged.pdf"
    markdown_to_merged(SECTIONS, out, fmt="pdf", channel_name="TestChannel")

    assert len(calls) == 1
    cmd = calls[0]
    metadata_flags = [a for a in cmd if a.startswith("--metadata=")]
    assert metadata_flags == []
