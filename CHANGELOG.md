# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.17.1] - 2026-07-01

### Added
- **Diagnostic for the YouTube "n challenge" failure** (the most common cause of *every video failing the same way* on a fresh VPS install). When `process_video()` detects the signature pattern — metadata fell back to defaults (`title='transcript'`/`'unknown'`, `duration=0`, `size=0`) **and** no subtitles were downloaded — it now prints a multi-line `EJS_HINT` after the regular "No subtitles available" warning, explaining that this is a missing-solver issue (not an IP block) and listing the three fix steps: install Node ≥ 22, `pipx install --force "yt-dlp[default]"`, and set `ytdlp_args = ["--js-runtimes", "node"]` in `config.toml`. New helpers: `yttranscript.ytdlp.looks_like_unsolved_n_challenge()` and `EJS_HINT` constant.
- README: new **"YouTube 'n challenge' / EJS"** subsection under the VPS deployment guide, with the symptom (`[youtube] VIDEO_ID: n challenge solving failed`), the root cause (yt-dlp's move to external JS solvers), and a verified one-time fix.

### Changed
- The VPS troubleshooting table now leads with "stale yt-dlp / missing EJS" before IP-block advice, reflecting real-world frequency.

## [2.17.0] - 2026-07-01

### Added
- **Network / anti-block options** for VPS and datacenter deployments where YouTube throttles the IP (Hetzner, OVH, Scaleway, …). New CLI flags and matching `config.toml` keys are forwarded to every `yt-dlp` invocation (subtitle download and Whisper fallback alike):
  - `--proxy URL` (socks5/http) — route through a proxy; **Cloudflare WARP** on `socks5://127.0.0.1:40000` is a free and effective option.
  - `--cookies PATH` — Netscape cookies file exported from a logged-in YouTube session (most reliable bypass).
  - `--cookies-from-browser BROWSER` — read cookies directly from a browser profile.
  - `--force-ipv4` — addresses the shared IPv6 `/64` rate-limiting common on OVH/Scaleway.
  - `--extractor-args 'youtube:player_client=-android'` — switch YouTube client (less-throttled ones: `-android`/`-ios`/`-tv`).
  - `--geo-bypass` — fake the X-Forwarded-For IP.
  - `--ytdlp-args '...'` — shell-quoted escape hatch appended verbatim (`--retries 10 --sleep-requests 1`, …). In `config.toml` accepts a TOML array: `ytdlp_args = ["--retries", "10"]`.
- New `NetworkOpts` dataclass in `yttranscript.ytdlp` is the single rendering point for these options; all yt-dlp call sites (`get_video_metadata`, `get_video_info`, `list_subs`, `try_download_subtitle`, `resolve_channel_videos`, `list_channel_videos`, the verbose `--list-subs`, and the Whisper audio download) accept and forward it.
- README: new **"VPS / datacenter deployment"** subsection under Configuration with a triage table and worked examples (force-ipv4 → cookies → WARP).

### Changed
- `yttranscript.config._toml_value` now renders lists as TOML arrays (so the generated template shows `ytdlp_args = []` correctly instead of a quoted string).

## [2.16.5] - 2026-06-14

### Fixed
- `--latest` and `--group` no longer crash with `FileNotFoundError` when `yt-dlp` is not installed. `resolve_channel_videos()` now calls `ensure_yt_dlp()` before invoking yt-dlp, so the runtime auto-install (pipx → pip → apt) fires on these paths just as it already did for single-video processing.
- The `--latest` and `--group` CLI branches are now wrapped in `try/except TranscriptError`, so install or resolution failures surface as clean error messages instead of raw Python tracebacks.

## [2.16.4] - 2026-06-14

### Changed
- yt-dlp auto-install now prefers `pipx` over `pip` as the first fallback (runtime `ytdlp.ensure_yt_dlp()` and Debian `postinst`). pipx installs yt-dlp into an isolated venv at `~/.local/bin`, avoiding PEP 668 `externally-managed-environment` errors on Debian 12+ / Ubuntu 23.04+ where system `pip install` is blocked. `pip` remains as a secondary fallback, followed by `brew`/`apt` as before. The `.deb` now declares `pipx` as a `Depends:` so the preferred path is always available.

### Fixed
- When `pipx install yt-dlp` succeeded but `~/.local/bin` was not yet on `PATH` for the current shell, the runtime auto-installer previously fell through to `pip install`, leaving yt-dlp installed twice (pipx venv + system pip). `ensure_yt_dlp()` now extends `PATH` with `~/.local/bin` in-process and, if yt-dlp is still not found, raises a clear `TranscriptError` instead of duplicating the install.
- Failure messages from `pipx`/`pip` are no longer hidden behind a generic "trying alternatives..." warning: the captured stderr is re-emitted via `debug()` (visible with `-v`) for easier diagnosis.

### Changed
- `yt-dlp` moved from a hard to an optional pip dependency (`pip install "yttranscript[ytdlp]"`). The Debian package no longer pulls `yt-dlp` via `${python3:Depends}`, avoiding stale apt versions on Debian 12 / Ubuntu LTS that triggered YouTube bot-detection errors. The `postinst` continues to install yt-dlp via pip when missing, and the runtime auto-install in `ytdlp.ensure_yt_dlp()` is unchanged. The pacman `PKGBUILD` still hard-requires `yt-dlp` (Arch rolling release is always current).

## [2.16.2] - 2026-06-14

### Fixed
- Debian `postinst` NOTE messages for missing `typst`/`himalaya` no longer claim they are installable via `apt` on Ubuntu 24.04+ — neither binary is packaged in any Ubuntu release. The NOTE now points to Debian 13 trixie+ as the `apt` source and to the upstream GitHub releases as the universal fallback.
- README "Dependencies" section clarifies that `apt install typst` / `apt install himalaya` only work on Debian 13+, and points to the new install scripts.

### Added
- `scripts/install-himalaya.sh` and `scripts/install-typst.sh`: download the latest static musl binary from GitHub releases (auto-detects `x86_64`/`aarch64`, supports `--version vX.Y.Z`) and install it into `/usr/local/bin`. Useful on Ubuntu and any distro without the apt package; no compilation required.

## [2.16.1] - 2026-06-14

### Added
- Multi-arch (`amd64`/`arm64`) Docker image (`Dockerfile` + `.dockerignore`) bundling `pandoc`, `typst` and `himalaya`, so PDF/EPUB/DOCX export and `--email TO` work out of the box. Runs as non-root uid 1000 with `XDG_CONFIG_HOME=/config`. README documents the build/run patterns and volume mounts.
- `himalaya` is now a `Recommends:` of the `.deb` (alongside `typst` and `pandoc`) and an `optdepends` of the pacman `PKGBUILD`, so a default `apt install` / `pacman -U` pulls it in on distros where it is packaged.

### Changed
- Debian `postinst` now prints a clear NOTE when `typst` or `himalaya` are absent from `PATH` (no auto-install attempt; mirrors the existing `yt-dlp` NOTE pattern).

## [2.16.0] - 2026-06-14

### Added
- `resolve_sender()` reads the sender (`From`) from the himalaya config: the account marked `default = true` (or the first account), combining `display-name` + `email` into `Name <email>`. Honors `$HIMALAYA_CONFIG` (colon-separated, first entry wins) and the XDG default `$XDG_CONFIG_HOME/himalaya/config.toml`. Fails with a clear `EmailError` if the config is missing, has no accounts, or the account lacks an `email` field.
- `_build_mime()` accepts a `sender` and sets the `From` header explicitly (previously left unset for himalaya to fill).

### Changed
- `send_email` now pipes the RFC 5322 message to `himalaya message send` over stdin instead of passing a temp `.eml` path as a positional argument. This is required by himalaya v1.2+, which treats positional args as inline message content (not paths) and dropped the `-f` flag. The temp file lifecycle is gone.
- README "Email output" section documents sender resolution and the stdin piping behavior.

## [2.15.0] - 2026-06-14

### Added
- Debian/Ubuntu packaging (`make deb`, `make deb-install`): builds a `.deb` via `dh-python` + `pybuild` from the existing `pyproject.toml`. The `debian/changelog` version is generated from the Makefile's `VERSION` (no fifth place to bump manually).
- `debian/` metadata: `control`, `rules`, `compat` (13), `postinst` (auto-installs `yt-dlp` via pip if missing, mirroring runtime behavior), `copyright`, `source/format` (native), `changelog.template`.
- CI job `build-deb` on every push/PR: builds, verifies (`dpkg-deb -I/-c`), checks the `/usr/bin/yttranscript` entry point, and uploads the `.deb` as a workflow artifact.
- Install instructions for Debian/Ubuntu in README.

### Changed
- CI `test` job now installs `typst` from the official statically-linked musl binary on GitHub releases (typst is not packaged in Ubuntu repos).
- `pdf.py` error messages mention both `pacman` and `apt` install commands for `pandoc` and `typst`.
- `README.md` Dependencies section lists `apt` equivalents.
- `.gitignore` covers debhelper artifacts (`*.deb`, `*.changes`, `*.buildinfo`, `debian/.debhelper/`, `debian/changelog`, etc.).
- `make clean` now removes both pacman and deb build artifacts.

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
