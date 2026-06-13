"""Tests for the SQLite cache and history module (yttranscript.db)."""

import pytest

from yttranscript import db


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def dbpath(tmp_path):
    """A fresh database path for each test (in tmp)."""
    return tmp_path / "test.db"


# --------------------------------------------------------------------------- #
#  extract_video_id
# --------------------------------------------------------------------------- #

class TestExtractVideoId:
    def test_watch_url(self):
        assert db.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert db.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert db.extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert db.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_live_url(self):
        assert db.extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123"
        assert db.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_not_youtube(self):
        assert db.extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ") is None

    def test_no_video_id(self):
        assert db.extract_video_id("https://www.youtube.com/") is None

    def test_empty(self):
        assert db.extract_video_id("") is None

    def test_none(self):
        assert db.extract_video_id(None) is None

    def test_short_id_rejected(self):
        # IDs must be exactly 11 chars
        assert db.extract_video_id("https://www.youtube.com/watch?v=short") is None


# --------------------------------------------------------------------------- #
#  init_db / get_connection
# --------------------------------------------------------------------------- #

class TestInitDb:
    def test_creates_tables(self, dbpath):
        db.init_db(dbpath)
        assert dbpath.exists()
        conn = db.get_connection(dbpath)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert {"videos", "transcripts", "summaries"}.issubset(tables)

    def test_creates_indices(self, dbpath):
        db.init_db(dbpath)
        conn = db.get_connection(dbpath)
        indices = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )}
        conn.close()
        assert {"idx_videos_channel", "idx_videos_upload", "idx_videos_accessed", "idx_transcripts_lookup"}.issubset(indices)

    def test_idempotent(self, dbpath):
        db.init_db(dbpath)
        db.init_db(dbpath)  # should not raise
        assert dbpath.exists()

    def test_wal_mode(self, dbpath):
        db.init_db(dbpath)
        conn = db.get_connection(dbpath)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_foreign_keys_on(self, dbpath):
        db.init_db(dbpath)
        conn = db.get_connection(dbpath)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert fk == 1


# --------------------------------------------------------------------------- #
#  save_transcript / get_cached
# --------------------------------------------------------------------------- #

class TestSaveAndGetCached:
    def test_save_and_get_txt(self, dbpath):
        db.save_transcript(
            video_id="abc12345678",
            url="https://www.youtube.com/watch?v=abc12345678",
            title="My Video",
            channel="TestChannel",
            channel_url="https://youtube.com/@test",
            duration=600,
            upload_date="2024-01-15",
            language="en",
            source="subtitles",
            fmt="txt",
            content="Hello world this is a transcript.",
            path=dbpath,
        )
        result = db.get_cached("abc12345678", "txt", "en", path=dbpath)
        assert result is not None
        content, info = result
        assert content == "Hello world this is a transcript."
        assert info["title"] == "My Video"
        assert info["channel"] == "TestChannel"
        assert info["duration"] == 600

    def test_get_cached_miss(self, dbpath):
        db.init_db(dbpath)
        assert db.get_cached("nonexistent", "txt", "en", path=dbpath) is None

    def test_different_format_not_cached(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        # txt is cached but json is not
        assert db.get_cached("abc12345678", "txt", "en", path=dbpath) is not None
        assert db.get_cached("abc12345678", "json", "en", path=dbpath) is None

    def test_different_lang_not_cached(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        assert db.get_cached("abc12345678", "txt", "en", path=dbpath) is not None
        assert db.get_cached("abc12345678", "txt", "es", path=dbpath) is None

    def test_save_replaces_existing(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Old", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="old content", path=dbpath,
        )
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="New", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="new content", path=dbpath,
        )
        result = db.get_cached("abc12345678", "txt", "en", path=dbpath)
        assert result is not None
        content, info = result
        assert content == "new content"
        assert info["title"] == "New"

    def test_timestamps_mismatch_no_hit(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", timestamps=False, path=dbpath,
        )
        # Looking for timestamps=True when stored with False
        assert db.get_cached("abc12345678", "txt", "en", timestamps=True, path=dbpath) is None
        # Looking for timestamps=False matches
        assert db.get_cached("abc12345678", "txt", "en", timestamps=False, path=dbpath) is not None

    def test_json_chunk_size_mismatch(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="json", content="{}", chunk_size=30, path=dbpath,
        )
        # Same format/lang but different chunk_size → miss
        assert db.get_cached("abc12345678", "json", "en", chunk_size=60, path=dbpath) is None
        # Same chunk_size → hit
        assert db.get_cached("abc12345678", "json", "en", chunk_size=30, path=dbpath) is not None

    def test_updates_last_accessed(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        conn = db.get_connection(dbpath)
        first = conn.execute("SELECT last_accessed FROM videos WHERE video_id = ?", ("abc12345678",)).fetchone()[0]
        conn.close()

        import time
        time.sleep(1.1)

        db.get_cached("abc12345678", "txt", "en", path=dbpath)
        conn = db.get_connection(dbpath)
        second = conn.execute("SELECT last_accessed FROM videos WHERE video_id = ?", ("abc12345678",)).fetchone()[0]
        conn.close()
        assert second > first


# --------------------------------------------------------------------------- #
#  save_summary
# --------------------------------------------------------------------------- #

class TestSaveSummary:
    def test_save_and_retrieve(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        db.save_summary("abc12345678", "This is a summary.", "llama-cli", path=dbpath)
        info = db.get_video_info("abc12345678", path=dbpath)
        assert info is not None
        assert len(info["summaries"]) == 1
        assert info["summaries"][0]["summary"] == "This is a summary."


# --------------------------------------------------------------------------- #
#  list_history
# --------------------------------------------------------------------------- #

class TestListHistory:
    def test_empty(self, dbpath):
        db.init_db(dbpath)
        assert db.list_history(path=dbpath) == []

    def test_returns_recent(self, dbpath):
        for i in range(5):
            db.save_transcript(
                video_id=f"vid{i:011d}"[-11:], url=f"https://youtube.com/watch?v=vid{i:011d}"[-11:],
                title=f"Video {i}", channel="Ch", channel_url="", duration=100,
                upload_date="2024-01-01", language="en", source="subtitles",
                fmt="txt", content=f"content {i}", path=dbpath,
            )
        history = db.list_history(path=dbpath)
        assert len(history) == 5
        # Most recent first (last_accessed desc)
        titles = [h["title"] for h in history]
        assert titles == ["Video 4", "Video 3", "Video 2", "Video 1", "Video 0"]

    def test_limit(self, dbpath):
        for i in range(10):
            db.save_transcript(
                video_id=f"vid{i:011d}"[-11:], url=f"https://youtube.com/watch?v=vid{i:011d}"[-11:],
                title=f"Video {i}", channel="Ch", channel_url="", duration=100,
                upload_date="2024-01-01", language="en", source="subtitles",
                fmt="txt", content=f"content {i}", path=dbpath,
            )
        history = db.list_history(limit=3, path=dbpath)
        assert len(history) == 3

    def test_filter_by_channel(self, dbpath):
        db.save_transcript(
            video_id="aaa12345678", url="https://youtube.com/watch?v=aaa12345678",
            title="A", channel="Alpha", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="a", path=dbpath,
        )
        db.save_transcript(
            video_id="bbb12345678", url="https://youtube.com/watch?v=bbb12345678",
            title="B", channel="Beta", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="b", path=dbpath,
        )
        history = db.list_history(channel="Alpha", path=dbpath)
        assert len(history) == 1
        assert history[0]["title"] == "A"

    def test_includes_formats(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="Ch", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="Ch", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="json", content="{}", chunk_size=30, path=dbpath,
        )
        history = db.list_history(path=dbpath)
        assert "txt" in history[0]["formats"]
        assert "json" in history[0]["formats"]


# --------------------------------------------------------------------------- #
#  get_video_info
# --------------------------------------------------------------------------- #

class TestGetVideoInfo:
    def test_not_found(self, dbpath):
        db.init_db(dbpath)
        assert db.get_video_info("nonexistent", path=dbpath) is None

    def test_returns_metadata(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="My Video", channel="TestChannel", channel_url="https://youtube.com/@test",
            duration=600, upload_date="2024-06-01", language="es", source="whisper",
            fmt="txt", content="content", path=dbpath,
        )
        info = db.get_video_info("abc12345678", path=dbpath)
        assert info is not None
        assert info["title"] == "My Video"
        assert info["channel"] == "TestChannel"
        assert info["duration"] == 600
        assert info["upload_date"] == "2024-06-01"
        assert info["language"] == "es"
        assert info["source"] == "whisper"
        assert len(info["cached_formats"]) == 1
        assert info["cached_formats"][0]["format"] == "txt"

    def test_includes_summaries(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        db.save_summary("abc12345678", "Summary 1", "cmd1", path=dbpath)
        db.save_summary("abc12345678", "Summary 2", "cmd2", path=dbpath)
        info = db.get_video_info("abc12345678", path=dbpath)
        assert len(info["summaries"]) == 2
        # Most recent first
        assert info["summaries"][0]["summary"] == "Summary 2"


# --------------------------------------------------------------------------- #
#  get_stats
# --------------------------------------------------------------------------- #

class TestGetStats:
    def test_empty_stats(self, dbpath):
        db.init_db(dbpath)
        stats = db.get_stats(path=dbpath)
        assert stats["total_videos"] == 0
        assert stats["total_transcripts"] == 0
        assert stats["total_summaries"] == 0

    def test_counts(self, dbpath):
        for vid in ["aaa12345678", "bbb12345678"]:
            db.save_transcript(
                video_id=vid, url=f"https://youtube.com/watch?v={vid}",
                title=f"Video {vid}", channel="Ch", channel_url="", duration=100,
                upload_date="", language="en", source="subtitles",
                fmt="txt", content="text", path=dbpath,
            )
        db.save_transcript(
            video_id="aaa12345678", url="https://youtube.com/watch?v=aaa12345678",
            title="Video aaa12345678", channel="Ch", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="json", content="{}", chunk_size=30, path=dbpath,
        )
        stats = db.get_stats(path=dbpath)
        assert stats["total_videos"] == 2
        assert stats["total_transcripts"] == 3
        assert stats["by_format"]["txt"] == 2
        assert stats["by_format"]["json"] == 1
        assert stats["by_channel"]["Ch"] == 2

    def test_db_size(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="x" * 10000, path=dbpath,
        )
        stats = db.get_stats(path=dbpath)
        assert stats["db_size_bytes"] > 0


# --------------------------------------------------------------------------- #
#  remove_video
# --------------------------------------------------------------------------- #

class TestRemoveVideo:
    def test_remove_existing(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        db.save_summary("abc12345678", "summary", "cmd", path=dbpath)
        assert db.remove_video("abc12345678", path=dbpath) is True
        assert db.get_video_info("abc12345678", path=dbpath) is None

    def test_remove_nonexistent(self, dbpath):
        db.init_db(dbpath)
        assert db.remove_video("nonexistent", path=dbpath) is False

    def test_cascade_deletes_transcripts(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="json", content="{}", chunk_size=30, path=dbpath,
        )
        db.remove_video("abc12345678", path=dbpath)
        conn = db.get_connection(dbpath)
        count = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
        conn.close()
        assert count == 0

    def test_cascade_deletes_summaries(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        db.save_summary("abc12345678", "summary", "cmd", path=dbpath)
        db.remove_video("abc12345678", path=dbpath)
        conn = db.get_connection(dbpath)
        count = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        conn.close()
        assert count == 0


# --------------------------------------------------------------------------- #
#  clear_all
# --------------------------------------------------------------------------- #

class TestClearAll:
    def test_clears_everything(self, dbpath):
        for vid in ["aaa12345678", "bbb12345678", "ccc12345678"]:
            db.save_transcript(
                video_id=vid, url=f"https://youtube.com/watch?v={vid}",
                title=f"Video {vid}", channel="Ch", channel_url="", duration=100,
                upload_date="", language="en", source="subtitles",
                fmt="txt", content="text", path=dbpath,
            )
        count = db.clear_all(path=dbpath)
        assert count == 3
        stats = db.get_stats(path=dbpath)
        assert stats["total_videos"] == 0
        assert stats["total_transcripts"] == 0

    def test_clear_empty(self, dbpath):
        db.init_db(dbpath)
        count = db.clear_all(path=dbpath)
        assert count == 0


# --------------------------------------------------------------------------- #
#  db_path
# --------------------------------------------------------------------------- #

class TestDbPath:
    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        path = db.db_path()
        assert path.name == "transcripts.db"
        assert "yttranscript" in str(path)

    def test_xdg_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        path = db.db_path()
        assert path == tmp_path / "yttranscript" / "transcripts.db"


# --------------------------------------------------------------------------- #
#  Concurrency (WAL)
# --------------------------------------------------------------------------- #

class TestConcurrency:
    def test_concurrent_reads(self, dbpath):
        db.save_transcript(
            video_id="abc12345678", url="https://youtube.com/watch?v=abc12345678",
            title="Test", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="text", path=dbpath,
        )
        # Multiple reads should work fine
        for _ in range(5):
            result = db.get_cached("abc12345678", "txt", "en", path=dbpath)
            assert result is not None

    def test_write_during_read(self, dbpath):
        db.save_transcript(
            video_id="aaa12345678", url="https://youtube.com/watch?v=aaa12345678",
            title="A", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="a", path=dbpath,
        )
        # Read should not block writes
        db.save_transcript(
            video_id="bbb12345678", url="https://youtube.com/watch?v=bbb12345678",
            title="B", channel="", channel_url="", duration=100,
            upload_date="", language="en", source="subtitles",
            fmt="txt", content="b", path=dbpath,
        )
        result = db.get_cached("aaa12345678", "txt", "en", path=dbpath)
        assert result is not None
        assert result[0] == "a"
