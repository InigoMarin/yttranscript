# AGENTS.md

## Commands

```bash
make lint      # pyflakes yttranscript tests (not ruff/flake8)
make test      # python -m pytest
make test-cov  # pytest --cov=yttranscript --cov-report=term-missing
```

Run a single test file or test:

```bash
pytest tests/test_vtt.py
pytest tests/test_cli.py::test_parser_has_url_positional
```

## Version bumps

Version is defined in **four** places — all must match:

1. `yttranscript/_version.py`
2. `pyproject.toml` (`version` field)
3. `Makefile` (`VERSION` variable)
4. `PKGBUILD` (`pkgver` variable)

## Architecture

Single Python package (`yttranscript/`) with entrypoint `yttranscript:main` (also `python -m yttranscript`).

- `cli.py` — argparse CLI, entry point
- `core.py` — `process_video()`: subtitle download pipeline
- `ytdlp.py` — yt-dlp wrapper for subtitle extraction
- `vtt.py` — VTT parsing and format conversion
- `whisper.py` — Whisper transcription fallback
- `summarize.py` — pipes transcript to external AI command
- `config.py` — XDG config loading (`~/.config/yttranscript/config.toml`)
- `web.py` — local web UI (HTTP server with SSE streaming)
- `pdf.py` — PDF/EPUB/DOCX export via Pandoc + Typst
- `log.py` — thread-local logging with verbosity levels
- `util.py` — shared helpers

Package data bundled: `web_ui.html`, `templates/*.typ`.

## Testing notes

- `conftest.py` adds repo root to `sys.path` — tests work without editable install
- pytest config: `--strict-markers` and `error::UserWarning` (UserWarnings fail tests)
- Fixtures: `sample_vtt_path`, `isolated_cwd`, `reset_log`

## Gotchas

- `src/` and `pkg/` are makepkg build artifacts (in `.gitignore`), not source directories
- Linter is **pyflakes** only — no style enforcer (no black/ruff/pycodestyle)
- PDF export requires external `pandoc` + `typst` installed on the system
- Whisper is an optional dependency (`pip install ".[whisper]"`)
