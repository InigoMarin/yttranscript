# yttranscript

CLI tool to download YouTube video transcripts (subtitles/captions) from the command line.
Falls back to OpenAI Whisper transcription when no subtitles are available.

## Install

### pip (any system)

```bash
pip install -e .
```

### Arch Linux

```bash
make pkg
sudo pacman -U yttranscript-*.pkg.tar.zst
```

Or step by step:

```bash
# 1. Create source tarball
mkdir -p yttranscript-1.8.1
cp yttranscript.py pyproject.toml README.md LICENSE yttranscript-1.8.1/
tar czf yttranscript-1.8.1.tar.gz yttranscript-1.8.1/

# 2. Build and install
makepkg -si

# 3. Clean up
rm -rf yttranscript-1.8.1 yttranscript-1.8.1.tar.gz
```

This installs the `yttranscript` command system-wide. Uninstall with `pacman -R yttranscript`.

## Usage

```bash
# Basic - auto-detect language, download transcript as plain text
yttranscript "https://www.youtube.com/watch?v=VIDEO_ID"

# Force specific language
yttranscript URL --lang es

# Output as VTT (with timestamps)
yttranscript URL --format vtt

# Include [MM:SS] timestamps in text output
yttranscript URL --timestamps

# JSON array output for RAG / vector DB ingestion
yttranscript URL --format json
yttranscript URL --format json --chunk-size 60 --stdout | python ingest.py

# Summarize with AI (pipes transcript to external command)
yttranscript URL --summarize
yttranscript URL --summarize --summarize-cmd "llama-cli -m model.gguf --temp 0.7"

# Start web UI (browser interface)
yttranscript --serve
yttranscript --serve --port 9090

# Custom output filename
yttranscript URL -o my_transcript

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
| `--lang` | Subtitle language code (default: auto-detect) |
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
| `-V, --version` | Show version |

### Whisper Models

| Model | Size | Speed | Accuracy |
|---|---|---|---|
| `tiny` | ~1 GB | Fastest | Lowest |
| `base` | ~1 GB | Fast | Good (default) |
| `small` | ~2 GB | Medium | Better |
| `medium` | ~5 GB | Slow | Very good |
| `large` | ~10 GB | Slowest | Best |

## Configuration

On first run, `yttranscript` creates a config file at `~/.config/yttranscript/config.toml`:

```toml
# Uncomment and edit to set your defaults
# CLI flags always override these values

lang = "es"
format = "txt"
timestamps = true
chunk_size = 30
# summarize_cmd = "llama-cli -m ~/.local/share/models/model.gguf --temp 0.7 -n 1024"
# summarize_prompt = "Summarize this video in bullet points"
whisper_model = "medium"
whisper_device = "gpu"
# whisper_dir = "/home/user/.cache/whisper"
```

Priority: **CLI flag** > **config file** > **hardcoded default**

Check your current config:

```bash
yttranscript --show-config
```

## Web UI

Start a local web interface:

```bash
yttranscript --serve
# → open http://localhost:8080 in your browser
```

Features:
- Paste YouTube URL and transcribe from the browser
- Select language, format (txt/json/vtt), timestamps, summarize
- Download results directly from the browser
- Runs on localhost only (no external access)

## Dependencies

- **yt-dlp** - installed automatically if missing
- **openai-whisper** - only needed for Whisper fallback, prompted before install
- **ffmpeg** - required by Whisper for audio processing

## How It Works

1. Auto-detect video language (or use `--lang`)
2. Try manual subtitles: exact lang → wildcard (e.g. `es.*`) → English fallback
3. Fall back to auto-generated subtitles (same language chain)
4. Last resort: download audio + transcribe with Whisper (GPU with CPU fallback)
5. Convert VTT to clean plain text (deduplicated lines, with video info header)

## Examples

```bash
# English video, auto-detect language
yttranscript "https://youtube.com/watch?v=dQw4w9WgXcQ"

# Spanish webinar, VTT format
yttranscript "https://youtube.com/watch?v=FWAXGxsvLxM" --format vtt

# Spanish video with timestamps for navigation
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --lang es --timestamps

# Transcribe with Whisper medium model on GPU
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --whisper --whisper-model medium

# Search for a keyword in transcript
yttranscript URL --stdout | grep -i "webhook"

# Copy transcript to clipboard without saving
yttranscript URL --stdout | wl-copy
```

## Summarization with AI

```bash
# Configure once in ~/.config/yttranscript/config.toml:
#   summarize_cmd = "llama-cli -m model.gguf --temp 0.7 -n 1024"
#   summarize_prompt = "Resume este video en puntos clave"

# Then just:
yttranscript URL --summarize

# Or specify inline:
yttranscript URL --summarize \
  --summarize-cmd "llama-cli -m model.gguf --temp 0.7 -n 1024" \
  --summarize-prompt "Resume en 5 bullets"
```

How it works: yttranscript downloads the transcript, extracts plain text, and pipes it as stdin to `summarize_cmd` with `summarize_prompt` prepended. Works with any CLI tool: llama.cpp, ollama, aichat, etc.

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
      "text": "Bienvenidos a esta presentacion..."
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
