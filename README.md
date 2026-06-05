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
mkdir -p yttranscript-1.7.0
cp yttranscript.py pyproject.toml README.md LICENSE yttranscript-1.7.0/
tar czf yttranscript-1.7.0.tar.gz yttranscript-1.7.0/

# 2. Build and install
makepkg -si

# 3. Clean up
rm -rf yttranscript-1.7.0 yttranscript-1.7.0.tar.gz
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

# Show current configuration
yttranscript --show-config

# Keep intermediate files
yttranscript URL --keep-vtt --keep-audio
```

## Options

| Flag | Description |
|---|---|
| `-o, --output` | Output filename (without extension). Default: video title. |
| `-f, --format` | `txt` (default) or `vtt` |
| `--lang` | Subtitle language code (default: auto-detect) |
| `--list-subs` | List available subtitles and exit |
| `--whisper` | Force Whisper transcription (skip subtitle download) |
| `--whisper-model` | Whisper model: `tiny`, `base` (default), `small`, `medium`, `large` |
| `--whisper-device` | Device for Whisper: `gpu` (default) or `cpu` |
| `--whisper-dir` | Directory to store Whisper models (default: `~/.cache/whisper/`) |
| `--stdout` | Output transcript to stdout for piping (no file saved) |
| `--keep-vtt` | Keep VTT file after text conversion |
| `--keep-audio` | Keep audio file after Whisper transcription |
| `--show-config` | Show current configuration and exit |
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
whisper_model = "medium"
whisper_device = "gpu"
# whisper_dir = "/home/user/.cache/whisper"
```

Priority: **CLI flag** > **config file** > **hardcoded default**

Check your current config:

```bash
yttranscript --show-config
```

## Dependencies

- **yt-dlp** - installed automatically if missing
- **openai-whisper** - only needed for Whisper fallback, prompted before install
- **ffmpeg** - required by Whisper for audio processing

## How It Works

1. Auto-detect video language (or use `--lang`)
2. Try manual subtitles (highest quality, human-created)
3. Fall back to auto-generated subtitles
4. Last resort: download audio + transcribe with Whisper (GPU with CPU fallback)
5. Convert VTT to clean plain text (deduplicated lines, with video info header)

## Examples

```bash
# English video, auto-detect language
yttranscript "https://youtube.com/watch?v=dQw4w9WgXcQ"

# Spanish webinar, VTT format
yttranscript "https://youtube.com/watch?v=FWAXGxsvLxM" --format vtt

# Transcribe with Whisper medium model on GPU
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --whisper --whisper-model medium

# Search for a keyword in transcript
yttranscript URL --stdout | grep -i "webhook"

# Copy transcript to clipboard without saving
yttranscript URL --stdout | wl-copy
```
