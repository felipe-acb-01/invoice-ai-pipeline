"""Every PDFium call the web app makes, behind one lock.

PDFium is not thread-safe, and FastAPI runs sync routes on a thread pool: a document of several pages, whose
images the browser asks for at once, used to kill the whole process (and every visitor's demo with it).
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

import pypdfium2 as pdfium

_LOCK = threading.Lock()


def page_count(source: Path | bytes) -> int:
    with _LOCK:
        doc = pdfium.PdfDocument(source)
        try:
            return len(doc)
        finally:
            doc.close()


def page_png(path: Path, page: int, scale: float = 1.6) -> bytes | None:
    """The page (1-based) as a PNG, or None if the document has no such page."""
    buf = io.BytesIO()
    with _LOCK:
        doc = pdfium.PdfDocument(path)
        try:
            if not 1 <= page <= len(doc):
                return None
            doc[page - 1].render(scale=scale).to_pil().save(buf, "PNG", optimize=True)
        finally:
            doc.close()
    return buf.getvalue()
