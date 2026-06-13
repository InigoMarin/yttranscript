# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.14.0] - 2026-06-13

### Added
- API summarization backend (`summarize_backend = "api"`): POSTs the transcript to an OpenAI-compatible chat completions endpoint via stdlib `urllib` — works with OpenAI, OpenRouter, LM Studio, vLLM, Ollama HTTP, Groq, z.ai, etc. No extra dependencies
- CLI flags: `--summarize-backend`, `--summarize-api-url`, `--summarize-api-model`, `--summarize-api-key-env`
- `--summarize-api-list-models` command: lists models accessible from the configured API endpoint (derives `GET /models` from the chat URL) and exits
- API key read from an environment variable (default `YTTRANSCRIPT_API_KEY`); never written to disk/config
- Backend selector (`cmd`/`api`) in the web UI

### Changed
- Extract duplicated helpers: `_resolve_options()`, `_parse_upload_date()`, `_merge_output_path()`
- Introduce `VideoInfo` dataclass to replace ad-hoc metadata dicts in `process_video()`
- Consolidate format sets: `PANDOC_FORMATS` reused in `web.py` instead of separate `_BINARY_FORMATS`
- Refactor `web._serve_api` into `_handle_binary` + `safe_send` (removed ~80 lines of duplicated try/except)

### Fixed
- Remove dead code: `get_video_title()`, `detect_video_language()`, `markdown_to_merged_pdf()`
- Config `port` key now respected by CLI via `resolve_value()`
- Detect NVIDIA GPU before Whisper to avoid wasted failed attempt on CPU-only hosts
- Declare `tomli` dependency for Python <3.11 (config was silently ignored without it)
- `__main__.py` now propagates non-zero exit codes instead of always exiting 0
- Restrict temp file permissions: `0o600` in summarize, `0o700` in web download dir

## [2.12.0] - 2026-06-13

### Added
- `--skip-cached` flag: skip processing if the video is already in cache

## [2.11.0] - 2026-06-13

### Changed
- Reuse cached transcript in summarize mode (skip subtitle download, pipe cached text to AI)
- Removed summaries table from SQLite cache (transcripts only)

## [2.10.0] - 2026-06-13

### Added
- SQLite cache for transcripts (`~/.local/share/yttranscript/transcripts.db`)
- CLI flags: `--no-cache`, `--history`, `--cache-clear`, `--cache-remove`, `--cache-info`, `--cache-stats`
- Config key: `cache_enabled` (default: true)
- Transcripts cached automatically; re-running the same URL is instant
- Cache lookup skips download even when `--summarize` is used

## [2.9.6] - 2026-06-12

### Added
- `--toc` for EPUB/DOCX merged documents

### Fixed
- Clickable TOC in merged PDFs using Typst `#outline`

## [2.9.0] - 2026-06-11

### Added
- Table of contents in merged PDF/EPUB/DOCX output
- Detect live streams and show clear error
- `--work-dir` option for intermediate files (private tempdir by default)
- Output no longer pollutes CWD with `transcript_temp*` / `audio_*` artifacts
