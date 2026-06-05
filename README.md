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
# 1. Create source tarball
mkdir -p yttranscript-1.0.0
cp yttranscript.py pyproject.toml README.md LICENSE yttranscript-1.0.0/
tar czf yttranscript-1.0.0.tar.gz yttranscript-1.0.0/

# 2. Build and install
makepkg -si

# 3. Clean up
rm -rf yttranscript-1.0.0 yttranscript-1.0.0.tar.gz
```

This installs the `yttranscript` command system-wide. Uninstall with `pacman -R yttranscript`.

## Usage

```bash
# Basic - download transcript as plain text (English by default)
yttranscript "https://www.youtube.com/watch?v=VIDEO_ID"

# Spanish video
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
yttranscript URL --whisper --whisper-model large

# Keep intermediate files
yttranscript URL --keep-vtt --keep-audio
```

## Options

| Flag | Description |
|---|---|
| `-o, --output` | Output filename (without extension). Default: video title. |
| `-f, --format` | `txt` (default) or `vtt` |
| `--lang` | Subtitle language code (default: `en`) |
| `--list-subs` | List available subtitles and exit |
| `--whisper` | Force Whisper transcription (skip subtitle download) |
| `--whisper-model` | Whisper model: `tiny`, `base` (default), `small`, `medium`, `large` |
| `--whisper-dir` | Directory to store Whisper models (default: `~/.cache/whisper/`) |
| `--keep-vtt` | Keep VTT file after text conversion |
| `--keep-audio` | Keep audio file after Whisper transcription |

### Whisper Models

| Model | Size | Speed | Accuracy |
|---|---|---|---|
| `tiny` | ~1 GB | Fastest | Lowest |
| `base` | ~1 GB | Fast | Good (default) |
| `small` | ~2 GB | Medium | Better |
| `medium` | ~5 GB | Slow | Very good |
| `large` | ~10 GB | Slowest | Best |

## Dependencies

- **yt-dlp** - installed automatically if missing
- **openai-whisper** - only needed for Whisper fallback, prompted before install
- **ffmpeg** - required by Whisper for audio processing

## How It Works

1. Try manual subtitles (highest quality, human-created)
2. Fall back to auto-generated subtitles
3. Last resort: download audio + transcribe with Whisper
4. Convert VTT to clean plain text (deduplicated lines)

## Examples

```bash
# English video, plain text output
yttranscript "https://youtube.com/watch?v=dQw4w9WgXcQ"

# Spanish webinar, VTT format
yttranscript "https://youtube.com/watch?v=FWAXGxsvLxM" --lang es --format vtt

# Transcribe with Whisper medium model
yttranscript "https://youtube.com/watch?v=VIDEO_ID" --whisper --whisper-model medium
```
