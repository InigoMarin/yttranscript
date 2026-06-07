# yttranscript

CLI tool to download YouTube video transcripts (subtitles/captions) from the command line.
Falls back to OpenAI Whisper transcription when no subtitles are available.

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

# Start web UI (browser interface)
yttranscript --serve
yttranscript --serve --port 9090

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
```

## Options

| Flag | Description |
|---|---|
| `-o, --output` | Output filename (without extension). Default: video title. |
| `-f, --format` | `txt` (default), `vtt`, or `json` (chunked for RAG) |
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
| `--summarize` | Pipe transcript to external AI command for summarization |
| `--summarize-cmd` | Command to pipe transcript to (config: `summarize_cmd`) |
| `--summarize-prompt` | Prompt prepended to transcript (config: `summarize_prompt`) |
| `--serve` | Start local web UI at `http://localhost:PORT` |
| `--port` | Port for web UI (default: 8080) |
| `--latest [N]` | List latest N videos from a channel (default: 10) |
| `--transcribe` | With `--latest`, transcribe all listed videos (batch mode). All other options apply to each video. |
| `--work-dir` | Directory for intermediate files (subtitle/audio/VTT). Default: private tempdir. |
| `--output-dir` | Directory where the final transcript is saved. Default: current directory. |
| `-V, --version` | Show version |

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
# fallback_lang = "en"
# whisper_model = "base"
# whisper_device = "gpu"
# whisper_dir = "/home/user/.cache/whisper"
```

Priority: **CLI flag** > **config file** > **hardcoded default**

Check your current config:

```bash
yttranscript --show-config
```

## Summarization with AI

```bash
# Configure once in ~/.config/yttranscript/config.toml:
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
- Select language, format (txt/json/vtt), timestamps, summarize
- Markdown rendering for txt and summarize output (headers, bold, lists)
- Download or copy results directly from the browser
- Runs on localhost only (no external access)
- CSRF protection (cross-origin browser requests blocked via `Origin` check)
- DNS-rebinding protection (`Host` header must be `localhost` / `127.0.0.1`)
- Concurrency limit (max 2 simultaneous transcriptions to prevent resource exhaustion)

## Environment Variables

| Variable | Effect |
|---|---|
| `XDG_CONFIG_HOME` | Override config directory (default: `~/.config`) |
| `NO_COLOR` | Disable ANSI color output (https://no-color.org) |
| `CLICOLOR` | Set to `0` to disable color |
| `CLICOLOR_FORCE` | Set to `1` to force color even when piped |

## Dependencies

- **yt-dlp** — declared as a pip dependency (installed with `pip install .`); if missing at runtime, auto-installed via pip with brew/apt fallback
- **openai-whisper** — only needed for Whisper fallback, prompted before install (install upfront with `pip install ".[whisper]"`)
- **ffmpeg** — required by Whisper for audio processing
- **script** (BSD/Linux `util-linux`) — required by `--summarize` to capture command output via pseudo-terminal (not available on Windows)

## How It Works

1. Auto-detect video language (or use `--lang`)
2. Try manual subtitles: exact lang → wildcard (e.g. `es.*`) → fallback language
3. Fall back to auto-generated subtitles (same language chain)
4. Last resort: download audio + transcribe with Whisper (GPU with CPU fallback)
5. Convert VTT to clean text with Markdown header (title, URL, duration, source)

Intermediate files (subtitles, audio) are written to a private temp directory by
default (`--work-dir` to override). The final transcript is saved to the current
directory (`--output-dir` to override).

## Examples

```bash
# English video, auto-detect language
yttranscript "https://youtube.com/watch?v=dQw4w9WgXcQ"

# Spanish webinar, VTT format
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --lang es --format vtt

# Spanish video with timestamps for navigation
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --lang es --timestamps

# Transcribe with Whisper medium model on GPU
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --whisper --whisper-model medium

# Search for a keyword in transcript
yttranscript URL --stdout | grep -i "webhook"

# Copy transcript to clipboard without saving
yttranscript URL --stdout | wl-copy
```
