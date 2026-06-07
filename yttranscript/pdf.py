"""Markdown to PDF conversion via weasyprint."""

from __future__ import annotations

from pathlib import Path

from .log import info


_PDF_CSS = """
@page { margin: 2cm; }
body { font-family: system-ui, sans-serif; font-size: 11pt; line-height: 1.6; color: #1e293b; }
h1 { color: #7c3aed; font-size: 1.5em; margin: 0 0 0.75em; }
h2 { font-size: 1.2em; margin: 1em 0 0.4em; }
h3 { font-size: 1.05em; margin: 0.8em 0 0.3em; }
p { margin: 0.35em 0; }
strong { font-weight: 700; }
code { font-family: monospace; background: #f1f5f9; padding: 0.1em 0.35em; border-radius: 3px; font-size: 0.9em; }
a { color: #7c3aed; text-decoration: underline; }
hr { border: none; border-top: 1px solid #cbd5e1; margin: 0.75em 0; }
ul { margin: 0.35em 0 0.35em 1.5em; }
li { margin: 0.15em 0; }
"""


def markdown_to_pdf(markdown_text: str, output_path: Path) -> None:
    """Convert markdown text to a styled PDF file.

    Uses the `markdown` library to convert MD → HTML, then weasyprint to
    render HTML → PDF with clean typography.
    """
    try:
        import markdown as md_lib
    except ImportError:
        raise ImportError(
            "PDF output requires the 'markdown' package. Install with: pip install markdown"
        )
    try:
        from weasyprint import HTML
    except ImportError:
        raise ImportError(
            "PDF output requires the 'weasyprint' package. Install with: pip install weasyprint"
        )

    info("Converting to PDF...")
    html_body = md_lib.markdown(markdown_text, extensions=["extra", "sane_lists"])
    html = f"<html><head><style>{_PDF_CSS}</style></head><body>{html_body}</body></html>"
    HTML(string=html).write_pdf(str(output_path))
