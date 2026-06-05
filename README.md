# yttranscript

Download YouTube video transcripts (subtitles/captions) from the command line.  
Falls back to Whisper transcription when no subtitles are available.

## Install

```bash
pip install -e .
```

This installs the `yttranscript` command globally.

## Usage

```bash
# Basic - download transcript as plain text
yttranscript "https://www.youtube.com/watch?v=VIDEO_ID"

# Specify language
yttranscript URL --lang es

# Output as VTT (with timestamps)
yttranscript URL --format vtt

# Custom output filename
yttranscript URL -o my_transcript

# List available subtitles
yttranscript URL --list-subs

# Force Whisper transcription (skip subtitle download)
yttranscript URL --whisper --whisper-model small

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
| `--whisper` | Force Whisper transcription |
| `--whisper-model` | `tiny`, `base` (default), `small`, `medium`, `large` |
| `--keep-vtt` | Keep VTT file after text conversion |
| `--keep-audio` | Keep audio file after Whisper transcription |

## Dependencies

- **yt-dlp** - installed automatically if missing
- **openai-whisper** - only needed for Whisper fallback, prompted before install

## How It Works

1. Try manual subtitles (highest quality)
2. Fall back to auto-generated subtitles
3. Last resort: download audio + transcribe with Whisper
4. Convert VTT to clean plain text (deduplicated lines)
