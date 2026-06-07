"""yttranscript: download YouTube video transcripts with Whisper fallback."""

from ._version import __version__
from .cli import main
from .core import process_video

__all__ = ["__version__", "main", "process_video"]
