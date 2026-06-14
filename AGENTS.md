# AGENTS.md

## Commands

```bash
make lint      # pyflakes yttranscript tests (not ruff/flake8)
make test      # python -m pytest
make test-cov  # pytest --cov=yttranscript --cov-report=term-missing
make pkg       # build pacman (.pkg.tar.zst) package — requires makepkg (Arch)
make deb       # build .deb package — requires dpkg-buildpackage (Debian/Ubuntu)
make clean     # remove all build artifacts (pacman + deb)
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

The `debian/changelog` version is **generated** from the Makefile's
`VERSION` at `make deb` time (via `debian/changelog.template`), so it is
*not* a fifth place to bump manually. Do not commit `debian/changelog`.

## Releases

GitHub Releases are produced automatically by `.github/workflows/release.yml`
when a tag matching `v*` is pushed. The workflow builds the `.deb` on
Ubuntu and publishes it with the corresponding `CHANGELOG.md` section as
release notes.

Release flow:

1. Bump version in the **four** places listed above.
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section at the top of `CHANGELOG.md`.
3. `git commit -am "Bump version to X.Y.Z"` and `git push`.
4. `git tag vX.Y.Z && git push --tags` — this fires the release workflow.
5. The Arch `.pkg.tar.zst` is **not** built by CI (GitHub has no native
   Arch runner); produce it locally with `make pkg` and attach it to the
   release with `gh release upload vX.Y.Z *.pkg.tar.zst` if desired.

## Architecture

Single Python package (`yttranscript/`) with entrypoint `yttranscript:main` (also `python -m yttranscript`).

- `cli.py` — argparse CLI, entry point
- `core.py` — `process_video()`: subtitle download pipeline
- `ytdlp.py` — yt-dlp wrapper for subtitle extraction
- `vtt.py` — VTT parsing and format conversion
- `whisper.py` — Whisper transcription fallback
- `summarize.py` — summarization backends: `cmd` (pipes transcript to external AI command via `script(1)` pseudo-terminal, BSD/Linux only) and `api` (POSTs to an OpenAI-compatible HTTP endpoint via stdlib `urllib`). Dispatcher `summarize()` selects by `backend`. `list_models()` + `derive_models_url()` power `--summarize-api-list-models`.
- `mail.py` — `--email TO` adapter: builds a MIME message (text body + attachment) and pipes it to `himalaya message send -f <eml>`. Validates recipient, raises `EmailError` (subclass of `TranscriptError`) if himalaya is missing.
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
- PDF/pandoc tests auto-skip if `pandoc` (or `typst`) is not installed — a full green run may have skipped tests

## Gotchas

- `src/` and `pkg/` are makepkg build artifacts (in `.gitignore`), not source directories
- `*.deb`, `*.changes`, `*.buildinfo`, `debian/.debhelper/`, `debian/files`, `debian/changelog` and `debian/yttranscript/` are debhelper artifacts (also in `.gitignore`)
- Linter is **pyflakes** only — no style enforcer (no black/ruff/pycodestyle)
- PDF export requires external `pandoc` + `typst` installed on the system
- Whisper requires `ffmpeg` and is an optional dependency (`pip install ".[whisper]"`)
- `yt-dlp` auto-installs itself at runtime if missing (pip → brew/apt fallback), so missing `yt-dlp` is not an error condition in the code
- `--email TO` requires `himalaya` to be installed and configured separately (no auto-install); used only when the flag is passed. The `.deb` lists `himalaya` (and `typst`) as `Recommends:` and the pacman `PKGBUILD` as `optdepends`, so a default `apt install` / `pacman -U` pulls them in on distros where they are packaged; the Debian `postinst` prints a NOTE when either is still missing.
