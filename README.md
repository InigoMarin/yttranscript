# yttranscript

CLI tool to download YouTube video transcripts (subtitles/captions) from the command line.
Falls back to OpenAI Whisper transcription when no subtitles are available.

Export to **txt**, **VTT**, **SRT**, **JSON** (chunked for RAG), **PDF**, **EPUB**, or **DOCX**.

## Features

- Auto-detect video language; tries manual → auto-generated subtitles → Whisper
- Channel groups: define named channel collections in config, transcribe all at once (`--group`)
- Batch mode: transcribe the latest N videos from a channel (`--latest`)
- AI summarization via external local command (llama-cli, Ollama, etc.) or OpenAI-compatible HTTP API
- `--merge` combines all summaries from a batch into a single PDF/EPUB/DOCX
- JSON output with configurable chunk size for RAG / vector DB ingestion
- Local web UI with real-time SSE progress streaming
- **SQLite cache**: transcripts are cached locally — re-running the same URL is instant
- XDG-compliant config file (`~/.config/yttranscript/config.toml`)
- `--email TO` sends the generated transcript as an attachment (via [himalaya](https://lib.rs/crates/himalaya))
- Zero config needed — sensible defaults, auto-installs yt-dlp

## Install

### pip (any system)

```bash
pip install .
```

With Whisper support pre-declared:

```bash
pip install ".[whisper]"
```

### Arch Linux

```bash
make pkg
sudo pacman -U yttranscript-*.pkg.tar.zst
```

This installs the `yttranscript` command system-wide. Uninstall with `pacman -R yttranscript`.

### Debian / Ubuntu

```bash
make deb
sudo apt install ../yttranscript_*.deb
```

This installs the `yttranscript` command system-wide. Uninstall with `sudo apt remove yttranscript`.
The first run will pull in `yt-dlp` via `pip` if the system package is missing or outdated.

Alternatively, download the prebuilt `.deb` from the
[Releases page](https://github.com/InigoMarin/yttranscript/releases) and
install it with `sudo apt install ./yttranscript_*.deb`.

### Development

```bash
pip install -e ".[dev]"
pytest
```

## Usage

```bash
# Basic — auto-detect language, download transcript as plain text
yttranscript "https://www.youtube.com/watch?v=VIDEO_ID"

# Force specific language
yttranscript URL --lang es

# Output as VTT (with timestamps)
yttranscript URL --format vtt

# Output as SRT (universal subtitle format for VLC, editors, etc.)
yttranscript URL --format srt

# Export as styled PDF
yttranscript URL --format pdf

# Export as EPUB e-book
yttranscript URL --format epub

# Export as DOCX (Word) document
yttranscript URL --format docx

# Include [MM:SS] timestamps in text output
yttranscript URL --timestamps

# JSON output for RAG / vector DB ingestion
yttranscript URL --format json
yttranscript URL --format json --chunk-size 60 --stdout | python ingest.py

# Summarize with AI (pipes transcript to external command)
yttranscript URL --summarize

# List latest videos from a channel
yttranscript "https://youtube.com/@channel" --latest
yttranscript "https://youtube.com/watch?v=..." --latest 5

# Transcribe the latest N videos from a channel (batch mode)
yttranscript "https://youtube.com/@channel" --latest 5 --transcribe

# Transcribe + summarize the latest 3
yttranscript "https://youtube.com/@channel" --latest 3 --transcribe --summarize

# Transcribe + summarize + merge into a single document
yttranscript "https://youtube.com/@channel" --latest 5 --transcribe --summarize --format pdf --merge
yttranscript "https://youtube.com/@channel" --latest 5 --transcribe --summarize --format epub --merge
yttranscript "https://youtube.com/@channel" --latest 5 --transcribe --summarize --format docx --merge

# Start web UI (browser interface)
yttranscript --serve
yttranscript --serve --port 9090

# Transcribe all channels in a group (defined in config.toml)
yttranscript --group tech --transcribe

# Transcribe latest 3 videos per channel in a group
yttranscript --group tech --latest 3 --transcribe

# Transcribe + summarize a group, merged into single PDF
yttranscript --group tech --transcribe --summarize --format pdf --merge

# Transcribe + summarize a group, merged into EPUB
yttranscript --group tech --transcribe --summarize --format epub --merge

# Combine group with language and output options
yttranscript --group tech --transcribe --lang es --output-dir ~/transcripts/

# Custom output filename or directory
yttranscript URL -o my_transcript
yttranscript URL --output-dir ~/transcripts/

# List available subtitles
yttranscript URL --list-subs

# Force Whisper transcription with a specific model
yttranscript URL --whisper
yttranscript URL --whisper --whisper-model medium
yttranscript URL --whisper --whisper-device cpu

# Pipe transcript to other commands (no file saved)
yttranscript URL --stdout | grep "keyword"
yttranscript URL --stdout | wl-copy

# Quiet mode (errors only, for scripts/CI)
yttranscript URL -q

# Verbose mode (debug: commands, yt-dlp/whisper output)
yttranscript URL -v

# Show current configuration
yttranscript --show-config

# Keep intermediate files
yttranscript URL --keep-vtt --keep-audio

# Re-download ignoring the cache
yttranscript URL --no-cache

# Skip if already cached (no file written, no AI run)
yttranscript URL --skip-cached
yttranscript --group news --latest 5 --transcribe --summarize --skip-cached

# List recently transcribed videos from cache
yttranscript --history
yttranscript --history 50

# Show cache statistics (totals, by format, by channel, DB size)
yttranscript --cache-stats

# Show cached metadata for a specific video
yttranscript --cache-info URL

# Remove a video from the cache
yttranscript --cache-remove URL

# Delete the entire cache
yttranscript --cache-clear
```

## Options

| Flag | Description |
|---|---|
| `-o, --output` | Output filename (without extension). Default: video title. |
| `-f, --format` | `txt` (default), `vtt`, `srt`, `json` (chunked for RAG), `pdf` (requires Pandoc + Typst), `epub` (requires Pandoc), or `docx` (requires Pandoc) |
| `--timestamps` | Include `[MM:SS]` timestamps in text output (config: `timestamps`) |
| `--chunk-size` | Seconds per chunk for JSON output (default: 30, config: `chunk_size`) |
| `--lang` | Subtitle language code (default: auto-detect, config: `lang`) |
| `--list-subs` | List available subtitles and exit |
| `--whisper` | Force Whisper transcription (skip subtitle download) |
| `--whisper-model` | Whisper model: `tiny`, `base` (default), `small`, `medium`, `large` |
| `--whisper-device` | Device for Whisper: `gpu` (default) or `cpu` |
| `--whisper-dir` | Directory to store Whisper models (default: `~/.cache/whisper/`) |
| `--stdout` | Output transcript to stdout for piping (no file saved) |
| `-q, --quiet` | Suppress all output except errors |
| `-v, --verbose` | Show debug output (commands, yt-dlp/whisper output) |
| `--keep-vtt` | Keep VTT file after text conversion |
| `--keep-audio` | Keep audio file after Whisper transcription |
| `--show-config` | Show current configuration and exit |
| `--summarize` | Summarize the transcript (uses backend `summarize_backend`: `cmd` or `api`) |
| `--summarize-backend` | Summarization backend: `cmd` (pipe to command) or `api` (HTTP endpoint). Default: `cmd` |
| `--summarize-cmd` | Command to pipe transcript to for backend `cmd` (config: `summarize_cmd`) |
| `--summarize-prompt` | Prompt prepended to transcript (config: `summarize_prompt`) |
| `--summarize-api-url` | OpenAI-compatible chat completions URL for backend `api` (config: `summarize_api_url`) |
| `--summarize-api-model` | Model name for backend `api` (config: `summarize_api_model`) |
| `--summarize-api-key-env` | Env var name holding the API key (default: `YTTRANSCRIPT_API_KEY`) |
| `--summarize-api-list-models` | List models accessible from the configured API endpoint and exit |
| `--serve` | Start local web UI at `http://localhost:PORT` |
| `--port` | Port for web UI (default: 8080) |
| `--latest [N]` | List latest N videos from a channel (default: 10) |
| `--transcribe` | With `--latest`, transcribe all listed videos (batch mode). All other options apply to each video. |
| `--merge` | With `--latest --transcribe --format pdf/epub/docx --summarize`, generate a single merged document with all summaries. |
| `--group` | Transcribe all channels in a named group from config (requires `--transcribe`). No URL needed. |
| `--work-dir` | Directory for intermediate files (subtitle/audio/VTT). Default: private tempdir. |
| `--output-dir` | Directory where the final transcript is saved. Default: current directory. |
| `-V, --version` | Show version |
| `--no-cache` | Skip cache lookup. Force re-download/transcription. |
| `--skip-cached` | Skip processing if the video is already in cache. Prints "Already in cache" and exits. |
| `--history [N]` | List N most recently transcribed videos from cache (default: 20) |
| `--cache-stats` | Show cache statistics (videos, formats, channels, DB size) |
| `--cache-info URL` | Show cached metadata for a video |
| `--cache-remove URL` | Remove a video from the cache by URL or video ID |
| `--cache-clear` | Delete all cached transcripts and history |

### Whisper Models

| Model | Size | Speed | Accuracy |
|---|---|---|---|
| `tiny` | ~75 MB | Fastest | Lowest |
| `base` | ~145 MB | Fast | Good (default) |
| `small` | ~480 MB | Medium | Better |
| `medium` | ~1.5 GB | Slow | Very good |
| `large` | ~3 GB | Slowest | Best |

## Configuration

On first run, `yttranscript` creates a config file. Location follows the XDG Base
Directory spec: `$XDG_CONFIG_HOME/yttranscript/config.toml` (defaults to
`~/.config/yttranscript/config.toml`):

```toml
# yttranscript configuration
# Uncomment and edit the lines below to set your defaults.
# CLI flags always override these values.

# lang = "es"
# format = "txt"
# timestamps = false
# chunk_size = 30
# summarize_cmd = "llama-cli -m ~/models/Llama-3.1-8B-Instruct-Q4_K_M.gguf -ngl 99 -fa 1 -ub 1024 -b 1024 --single-turn"
# summarize_prompt = "Summarize this video in bullet points. Format for readability using markdown."
# summarize_timeout = 300
# summarize_backend = "cmd"
# summarize_api_url = "https://api.openai.com/v1/chat/completions"
# summarize_api_model = "gpt-4o-mini"
# summarize_api_key_env = "YTTRANSCRIPT_API_KEY"
# fallback_lang = "en"
# whisper_model = "base"
# whisper_device = "gpu"
# whisper_dir = "/home/user/.cache/whisper"
# cache_enabled = true
```

Priority: **CLI flag** > **config file** > **hardcoded default**

Check your current config:

```bash
yttranscript --show-config
```

### Channel Groups

Define named collections of YouTube channels in the `[channels]` section of
`config.toml`. Each group is a name mapping to a list of channel URLs:

```toml
[channels]
tech = [
    "https://www.youtube.com/@Fireship",
    "https://www.youtube.com/@ThePrimeagen",
    "https://www.youtube.com/@TheCodingTrain",
]
news = [
    "https://www.youtube.com/@BBCNews",
    "https://www.youtube.com/@CNN",
]
learning = [
    "https://www.youtube.com/@3Blue1Brown",
    "https://www.youtube.com/@MITOpenCourseWare",
]
```

Then transcribe all channels in a group with `--group`:

```bash
yttranscript --group tech --transcribe
```

Each URL in the group is resolved to its channel, the latest N videos are
fetched (default 10, override with `--latest`), and transcribed sequentially.
All standard options (`--format`, `--lang`, `--summarize`, etc.) apply to
every video in the group.

When using `--merge` with a group, the merged output file is named after the
group (e.g., `tech.pdf`) unless `--output` is specified.

`--group` requires `--transcribe`. No positional URL is needed when using
`--group`.

Non-YouTube URLs in a group are automatically skipped with a warning.

List your groups and verify config:

```bash
yttranscript --show-config
```

This displays all config values plus any channel groups you have defined.

## Summarization with AI

yttranscript supports two summarization backends, selected via `summarize_backend`:

- **`cmd`** (default): pipes the transcript to an external local command (e.g. `llama-cli`, Ollama). No network, fully private, but consumes local GPU/CPU/RAM.
- **`api`**: POSTs the transcript to an OpenAI-compatible chat completions endpoint (OpenAI, OpenRouter, LM Studio server, vLLM, Ollama HTTP, Groq, Together, ...). Light on local resources, but sends the transcript over the network and requires an API key.

### Backend `cmd` (local command)

```bash
# Configure once in ~/.config/yttranscript/config.toml:
#   summarize_backend = "cmd"
#   summarize_cmd = "llama-cli -m ~/models/Llama-3.1-8B-Instruct-Q4_K_M.gguf -ngl 99 -fa 1 -ub 1024 -b 1024 --single-turn"
#   summarize_prompt = "Summarize this video in bullet points. Format for readability using markdown."

# Then just:
yttranscript URL --summarize

# Or specify inline:
yttranscript URL --summarize \
  --summarize-cmd "llama-cli -m ~/models/Llama-3.1-8B-Instruct-Q4_K_M.gguf -ngl 99 --single-turn" \
  --summarize-prompt "Summarize in 5 bullet points"
```

How it works: yttranscript downloads the transcript, extracts plain text, and sends it to `summarize_cmd` with `summarize_prompt` prepended. Output is captured via a pseudo-terminal (`script(1)`) and cleaned (banner, stats, thinking blocks removed). The timeout is configurable via `summarize_timeout` in the config. Currently optimized for llama.cpp's `llama-cli`; other tools may work but output parsing is tailored to llama-cli's format.

### Backend `api` (HTTP endpoint)

```bash
# 1. Set your API key (env var only — never put it in the config file):
#    Bash:       export YTTRANSCRIPT_API_KEY="sk-..."
#    Fish:       set -Ux YTTRANSCRIPT_API_KEY "sk-..."
#    Systemd:    Environment="YTTRANSCRIPT_API_KEY=sk-..."

# 2. Configure in ~/.config/yttranscript/config.toml:
#   summarize_backend    = "api"
#   summarize_api_url    = "https://api.openai.com/v1/chat/completions"
#   summarize_api_model  = "gpt-4o-mini"
#   summarize_prompt     = "Summarize this video in bullet points."

# 3. Run:
yttranscript URL --summarize

# Or fully inline (the env var is still read from the environment):
yttranscript URL --summarize \
  --summarize-backend api \
  --summarize-api-url "https://api.openai.com/v1/chat/completions" \
  --summarize-api-model "gpt-4o-mini"
```

How it works: yttranscript POSTs a chat-completions request (`{model, messages, temperature: 0.3}`) with `summarize_prompt` + transcript as the user message. The response `choices[0].message.content` is returned as the summary. Uses only stdlib `urllib` — no extra dependencies. The API key is read from the environment variable named by `summarize_api_key_env` (default: `YTTRANSCRIPT_API_KEY`); to reuse an existing var, set `--summarize-api-key-env OPENAI_API_KEY`.

Other OpenAI-compatible endpoints work by changing `summarize_api_url` + `summarize_api_model`, e.g. OpenRouter (`https://openrouter.ai/api/v1/chat/completions`), a local LM Studio server (`http://localhost:1234/v1/chat/completions`), Ollama's OpenAI shim (`http://localhost:11434/v1/chat/completions`), Groq, Together, etc.

### Discovering accessible models

To list the models your API key can use (helpful before picking `summarize_api_model`):

```bash
# Requires summarize_api_url in config (or --summarize-api-url) and the API key env var.
yttranscript --summarize-api-list-models

# Pipe to a fuzzy finder to pick one:
yttranscript --summarize-api-list-models | grep gpt
```

This derives the `GET /models` endpoint from `summarize_api_url` (replacing `/chat/completions` with `/models`) and prints a table of `ID`, `Owner`, and `Created` date, sorted alphabetically.

## JSON Output

```bash
yttranscript URL --format json --stdout
yttranscript URL --format json -o my_transcript
```

Output structure:

```json
{
  "title": "Video Title",
  "url": "https://youtube.com/watch?v=...",
  "duration": 1800,
  "source": "subtitles",
  "chunk_size": 30,
  "chunks": [
    {
      "start": "00:00",
      "end": "00:30",
      "start_seconds": 0,
      "end_seconds": 30,
      "text": "Welcome to this presentation..."
    }
  ]
}
```

Ingest with Python:

```python
import json, sys

data = json.load(sys.stdin)
for chunk in data["chunks"]:
    doc = {
        "text": chunk["text"],
        "metadata": {
            "title": data["title"],
            "url": data["url"],
            "start": chunk["start"],
            "deep_link": f"{data['url']}&t={chunk['start_seconds']}",
        },
    }
    vector_db.add(doc)
```

## Web UI

Start a local web interface:

```bash
yttranscript --serve
# → open http://localhost:8080 in your browser
```

Features:
- Paste YouTube URL and transcribe from the browser
- Real-time progress streaming via SSE (see each subtitle attempt, Whisper progress)
- Cancel button to abort in-progress transcription
- Select language, format (txt/json/vtt/srt/epub/docx), timestamps, summarize
- Markdown rendering for txt and summarize output (headers, bold, lists)
- Browser notifications when transcription completes (enable via the bell icon in the header; falls back to flashing the tab title)
- Download or copy results directly from the browser
- Runs on localhost only (no external access)
- CSRF protection (cross-origin browser requests blocked via `Origin` check)
- DNS-rebinding protection (`Host` header must be `localhost` / `127.0.0.1`)
- Concurrency limit (max 2 simultaneous transcriptions to prevent resource exhaustion)

## Email output

Send the generated transcript as an email attachment using [himalaya](https://lib.rs/crates/himalaya) (must be installed and configured separately):

```bash
# Send a PDF to a single recipient
yttranscript URL --format pdf --email friend@example.com

# Send an EPUB to a Kindle address
yttranscript URL --format epub --email name@kindle.com

# Batch: send the merged PDF (per-video emails are blocked to avoid spam)
yttranscript URL --latest 5 --transcribe --summarize --merge --email me@example.com
```

The email subject is the file name and the body contains the video metadata (title, channel, URL, language, duration, upload date). `--email` validates the recipient address and fails fast with a clear error if `himalaya` is not in `$PATH`.

The **sender** (`From`) is resolved from your himalaya config: yttranscript reads the account marked `default = true` (or the first account if none is marked), combining its `display-name` and `email` into a `Name <email@example.com>` header. The config is located via `$HIMALAYA_CONFIG` (colon-separated, first entry wins) or the XDG default `$XDG_CONFIG_HOME/himalaya/config.toml` (`~/.config/himalaya/config.toml`). If the config is missing, has no accounts, or the account lacks an `email` field, `--email` fails with a clear error.

The RFC 5322 message is piped to `himalaya message send` over stdin (required by himalaya v1.2+, which no longer accepts a positional message path).

## Environment Variables

| Variable | Effect |
|---|---|
| `XDG_CONFIG_HOME` | Override config directory (default: `~/.config`) |
| `XDG_DATA_HOME` | Override data/cache directory for SQLite DB (default: `~/.local/share`) |
| `NO_COLOR` | Disable ANSI color output (https://no-color.org) |
| `CLICOLOR` | Set to `0` to disable color |
| `CLICOLOR_FORCE` | Set to `1` to force color even when piped |

## Dependencies

- **yt-dlp** — declared as a pip dependency (installed with `pip install .`); if missing at runtime, auto-installed via pip with brew/apt fallback
- **openai-whisper** — only needed for Whisper fallback, prompted before install (install upfront with `pip install ".[whisper]"`)
- **pandoc** — required for PDF, EPUB, and DOCX export (`pacman -S pandoc` / `apt install pandoc` / https://pandoc.org/installing.html)
- **typst** — additionally required for PDF export (`pacman -S typst` / `apt install typst`)
- **ffmpeg** — required by Whisper for audio processing (`pacman -S ffmpeg` / `apt install ffmpeg`)
- **script** (BSD/Linux `util-linux`) — required by `--summarize` to capture command output via pseudo-terminal (not available on Windows)
- **himalaya** — required only by `--email TO` (`pacman -S himalaya` / `cargo install himalaya` / https://lib.rs/crates/himalaya)

## How It Works

1. Auto-detect video language (or use `--lang`)
2. Try manual subtitles: exact lang → wildcard (e.g. `es.*`) → fallback language
3. Fall back to auto-generated subtitles (same language chain)
4. Last resort: download audio + transcribe with Whisper (GPU with CPU fallback)
5. Convert VTT to the chosen output format (txt, vtt, srt, json, pdf, epub, docx)

Intermediate files (subtitles, audio) are written to a private temp directory by
default (`--work-dir` to override). The final transcript is saved to the current
directory (`--output-dir` to override).

## Transcript Cache

Every successful transcription is automatically stored in a local SQLite
database at `~/.local/share/yttranscript/transcripts.db` (override with
`$XDG_DATA_HOME`). Re-running the same URL+language+format combination
returns instantly from cache — no network calls, no subtitle downloads.

The cache stores video metadata (title, channel, duration, upload date,
language) and the transcript text.

When used with `--summarize`, the cached transcript is piped directly to
the summarizer without re-downloading subtitles.

Use `--skip-cached` to skip already-processed videos entirely — prints
"Already in cache" and exits without writing any file or running the AI.
Ideal in batch mode to only process new videos.

```bash
# Normal run — downloads and caches
yttranscript URL

# Second run — served from cache instantly
yttranscript URL

# Force re-download (ignore cache)
yttranscript URL --no-cache

# Skip if already cached (no processing, no file written)
yttranscript URL --skip-cached

# Batch: only process videos not yet in cache
yttranscript --group news --latest 5 --transcribe --summarize --skip-cached

# View history
yttranscript --history          # last 20
yttranscript --history 50       # last 50

# Check stats
yttranscript --cache-stats
#   Total videos:      42
#   Total transcripts: 58
#   By format:         txt=42, json=12, vtt=4
#   Top channels:      Fireship=18, Primeagen=15, ...
#   Database size:     2.3 MB

# Inspect or manage individual entries
yttranscript --cache-info URL
yttranscript --cache-remove URL
yttranscript --cache-clear
```

Disable caching entirely in `config.toml`:

```toml
cache_enabled = false
```

## Examples

```bash
# English video, auto-detect language
yttranscript "https://youtube.com/watch?v=dQw4w9WgXcQ"

# Spanish webinar, VTT format
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --lang es --format vtt

# Export as SRT subtitles for a video editor / VLC
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --format srt

# Export as EPUB for reading on an e-reader
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --format epub

# Export as DOCX for editing in Word / Google Docs
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --format docx

# Spanish video with timestamps for navigation
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --lang es --timestamps

# Transcribe with Whisper medium model on GPU
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --whisper --whisper-model medium

# Search for a keyword in transcript
yttranscript URL --stdout | grep -i "webhook"

# Copy transcript to clipboard without saving
yttranscript URL --stdout | wl-copy

# Transcribe all channels in the "tech" group
yttranscript --group tech --transcribe

# Latest 5 videos per channel in the "news" group
yttranscript --group news --latest 5 --transcribe

# Transcribe + summarize "learning" group, merged into a single EPUB
yttranscript --group learning --transcribe --summarize --format epub --merge

# Transcribe group with custom output directory and language
yttranscript --group tech --transcribe --lang en --output-dir ~/transcripts/tech/

# Transcribe group with Whisper fallback
yttranscript --group tech --transcribe --whisper
```
