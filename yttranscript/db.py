"""SQLite cache and history for transcripts.

Zero external dependencies — uses only the stdlib ``sqlite3`` module.
The database lives at ``$XDG_DATA_HOME/yttranscript/transcripts.db``
(default ``~/.local/share/yttranscript/transcripts.db``).
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# --------------------------------------------------------------------------- #
#  Path resolution
# --------------------------------------------------------------------------- #

def db_path() -> Path:
    """Resolve the database location honouring ``$XDG_DATA_HOME``."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "yttranscript" / "transcripts.db"
    return Path.home() / ".local" / "share" / "yttranscript" / "transcripts.db"


# --------------------------------------------------------------------------- #
#  Video-ID extraction
# --------------------------------------------------------------------------- #

_VIDEO_ID_RE = re.compile(
    r"(?:watch\?v=|youtu\.be/|embed/|shorts/|live/)([A-Za-z0-9_-]{11})"
)

_YT_DOMAIN_RE = re.compile(
    r"(?:youtube\.com|youtu\.be|youtube-nocookie\.com)", re.IGNORECASE,
)


def extract_video_id(url: str) -> str | None:
    """Extract the 11-char YouTube video ID from a URL.

    Supports ``watch?v=``, ``youtu.be/``, ``/embed/``, ``/shorts/``, ``/live/``.
    Returns ``None`` when the URL is not from YouTube or no ID is found.
    """
    if not url or not _YT_DOMAIN_RE.search(url):
        return None
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
#  Connection / schema
# --------------------------------------------------------------------------- #

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id      TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    channel       TEXT,
    channel_url   TEXT,
    duration      INTEGER,
    upload_date   TEXT,
    language      TEXT,
    source        TEXT,
    first_seen    TEXT NOT NULL,
    last_accessed TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    format        TEXT NOT NULL,
    language      TEXT NOT NULL,
    content       TEXT NOT NULL,
    timestamps    INTEGER DEFAULT 0,
    chunk_size    INTEGER,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE,
    UNIQUE(video_id, format, language)
);

CREATE TABLE IF NOT EXISTS summaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    summary       TEXT NOT NULL,
    summarize_cmd TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_videos_channel
    ON videos(channel);
CREATE INDEX IF NOT EXISTS idx_videos_upload
    ON videos(upload_date);
CREATE INDEX IF NOT EXISTS idx_videos_accessed
    ON videos(last_accessed);
CREATE INDEX IF NOT EXISTS idx_transcripts_lookup
    ON transcripts(video_id, format, language);
"""


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and foreign keys enabled.

    ``check_same_thread=False`` so the connection can be shared across the
    threaded web server.  Each public function opens and closes its own
    connection — SQLite handles the pooling internally.
    """
    db_file = path or db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_file),
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> None:
    """Create tables and indices if they don't exist yet.  Idempotent."""
    conn = get_connection(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _now() -> str:
    """UTC timestamp in ISO-8601 (sortable)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
#  Cache: lookup + save
# --------------------------------------------------------------------------- #

def get_cached(
    video_id: str,
    fmt: str,
    lang: str,
    timestamps: bool = False,
    chunk_size: int | None = None,
    path: Path | None = None,
) -> tuple[str, dict] | None:
    """Look up a cached transcript.

    Returns ``(content, video_info_dict)`` or ``None`` if not cached.
    The ``video_info`` dict mirrors the shape used by ``core.py`` so the
    caller can use it directly.
    """
    init_db(path)
    conn = get_connection(path)
    try:
        row = conn.execute(
            """SELECT t.content, t.timestamps, t.chunk_size,
                      v.title, v.url, v.channel, v.duration,
                      v.upload_date, v.language, v.source
               FROM transcripts t
               JOIN videos v ON v.video_id = t.video_id
               WHERE t.video_id = ?
                 AND t.format   = ?
                 AND t.language = ?""",
            (video_id, fmt, lang),
        ).fetchone()

        if row is None:
            return None

        # For JSON format the chunk_size must also match.
        if fmt == "json" and chunk_size is not None and row["chunk_size"] != chunk_size:
            return None

        # For txt format timestamps must match.
        if fmt == "txt" and bool(row["timestamps"]) != timestamps:
            return None

        content = row["content"]
        video_info = {
            "title": row["title"],
            "url": row["url"],
            "duration": row["duration"],
            "channel": row["channel"] or "",
            "upload_date": row["upload_date"] or "",
            "language": row["language"],
            "source": row["source"],
        }
        # Update last_accessed for LRU-style insights.
        conn.execute(
            "UPDATE videos SET last_accessed = ? WHERE video_id = ?",
            (_now(), video_id),
        )
        conn.commit()
        return (content, video_info)
    finally:
        conn.close()


def save_transcript(
    video_id: str,
    url: str,
    title: str,
    channel: str,
    channel_url: str,
    duration: int,
    upload_date: str,
    language: str,
    source: str,
    fmt: str,
    content: str,
    timestamps: bool = False,
    chunk_size: int | None = None,
    path: Path | None = None,
) -> None:
    """Insert or replace a video and its transcript record."""
    init_db(path)
    now = _now()
    conn = get_connection(path)
    try:
        conn.execute(
            """INSERT INTO videos (video_id, url, title, channel, channel_url,
                                   duration, upload_date, language, source,
                                   first_seen, last_accessed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET
                   url           = excluded.url,
                   title         = excluded.title,
                   channel       = excluded.channel,
                   channel_url   = excluded.channel_url,
                   duration      = excluded.duration,
                   upload_date   = excluded.upload_date,
                   language      = excluded.language,
                   source        = excluded.source,
                   last_accessed = excluded.last_accessed""",
            (video_id, url, title, channel, channel_url,
             duration, upload_date, language, source, now, now),
        )
        conn.execute(
            """INSERT INTO transcripts
                   (video_id, format, language, content, timestamps, chunk_size, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(video_id, format, language) DO UPDATE SET
                   content    = excluded.content,
                   timestamps = excluded.timestamps,
                   chunk_size = excluded.chunk_size,
                   created_at = excluded.created_at""",
            (video_id, fmt, language, content,
             1 if timestamps else 0, chunk_size, now),
        )
        conn.commit()
    finally:
        conn.close()


def save_summary(
    video_id: str,
    summary: str,
    summarize_cmd: str,
    path: Path | None = None,
) -> None:
    """Store an AI-generated summary for a video."""
    init_db(path)
    conn = get_connection(path)
    try:
        conn.execute(
            """INSERT INTO summaries (video_id, summary, summarize_cmd, created_at)
               VALUES (?, ?, ?, ?)""",
            (video_id, summary, summarize_cmd, _now()),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  History / queries
# --------------------------------------------------------------------------- #

def list_history(
    limit: int = 20,
    channel: str | None = None,
    path: Path | None = None,
) -> list[dict]:
    """Return recently transcribed videos, most recent first.

    Each dict has keys: ``video_id, url, title, channel, duration,
    upload_date, language, source, first_seen, last_accessed,
    formats`` (comma-separated list of cached formats).
    """
    init_db(path)
    conn = get_connection(path)
    try:
        query = """SELECT v.*, GROUP_CONCAT(DISTINCT t.format) AS formats
                   FROM videos v
                   LEFT JOIN transcripts t ON t.video_id = v.video_id"""
        params: list = []
        if channel:
            query += " WHERE v.channel = ?"
            params.append(channel)
        query += " GROUP BY v.video_id ORDER BY v.last_accessed DESC, v.rowid DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_video_info(video_id: str, path: Path | None = None) -> dict | None:
    """Return stored metadata for a single video, or ``None``."""
    init_db(path)
    conn = get_connection(path)
    try:
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        # Attach cached formats.
        fmts = conn.execute(
            "SELECT format, language FROM transcripts WHERE video_id = ?",
            (video_id,),
        ).fetchall()
        result["cached_formats"] = [
            {"format": f["format"], "language": f["language"]} for f in fmts
        ]
        # Attach summaries.
        summaries = conn.execute(
            "SELECT summary, created_at FROM summaries WHERE video_id = ? ORDER BY id DESC",
            (video_id,),
        ).fetchall()
        result["summaries"] = [dict(s) for s in summaries]
        return result
    finally:
        conn.close()


def get_stats(path: Path | None = None) -> dict:
    """Return aggregate statistics about the cache."""
    init_db(path)
    conn = get_connection(path)
    try:
        total_videos = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        total_transcripts = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
        total_summaries = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]

        by_format = {
            r["format"]: r["count"]
            for r in conn.execute(
                "SELECT format, COUNT(*) as count FROM transcripts GROUP BY format"
            ).fetchall()
        }

        by_channel_rows = conn.execute(
            """SELECT channel, COUNT(*) as count
               FROM videos
               WHERE channel IS NOT NULL AND channel != ''
               GROUP BY channel ORDER BY count DESC LIMIT 10"""
        ).fetchall()
        by_channel = {r["channel"]: r["count"] for r in by_channel_rows}

        # Database file size.
        db_file = path or db_path()
        db_size = db_file.stat().st_size if db_file.exists() else 0

        return {
            "total_videos": total_videos,
            "total_transcripts": total_transcripts,
            "total_summaries": total_summaries,
            "by_format": by_format,
            "by_channel": by_channel,
            "db_size_bytes": db_size,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  Management
# --------------------------------------------------------------------------- #

def remove_video(video_id: str, path: Path | None = None) -> bool:
    """Delete a video and all its transcripts/summaries.

    Returns ``True`` if the video existed, ``False`` otherwise.
    """
    init_db(path)
    conn = get_connection(path)
    try:
        cur = conn.execute(
            "DELETE FROM videos WHERE video_id = ?", (video_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_all(path: Path | None = None) -> int:
    """Delete everything. Returns count of videos removed."""
    init_db(path)
    conn = get_connection(path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        conn.execute("DELETE FROM transcripts")
        conn.execute("DELETE FROM summaries")
        conn.execute("DELETE FROM videos")
        conn.commit()
        return count
    finally:
        conn.close()
