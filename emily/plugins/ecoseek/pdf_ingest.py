"""PDF ingestion pipeline for user-uploaded documents.

Extracts text from PDFs and indexes them in litdb for FTS5 search.
Used by the ``upload_document`` tool so users can load their own papers
and have DiDAL reference them during literature retrieval.

Dependencies:
    pdfplumber (preferred) or PyMuPDF (fitz) — added to Emily Dockerfile.
    Falls back to a no-op if neither is available.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# Upload directory for user PDFs
_UPLOAD_DIR = os.environ.get(
    "ECOSEEK_UPLOAD_DIR",
    os.path.expanduser("~/.ecoseek/uploads"),
)


def extract_text_from_pdf(pdf_path: str) -> dict:
    """Extract text and metadata from a PDF file.

    Tries pdfplumber first (better table/layout extraction),
    falls back to PyMuPDF (fitz), then returns error if neither available.

    Returns
    -------
    dict
        {text, num_pages, title, authors, year, abstract, error}
    """
    if not os.path.isfile(pdf_path):
        return {"text": "", "error": f"File not found: {pdf_path}"}

    # Try pdfplumber
    try:
        return _extract_pdfplumber(pdf_path)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("pdfplumber failed for %s: %s", pdf_path, exc)

    # Try PyMuPDF (fitz)
    try:
        return _extract_pymupdf(pdf_path)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("PyMuPDF failed for %s: %s", pdf_path, exc)

    return {
        "text": "",
        "error": "No PDF library available. Install pdfplumber or PyMuPDF.",
    }


def _extract_pdfplumber(pdf_path: str) -> dict:
    """Extract text using pdfplumber."""
    import pdfplumber

    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)

    full_text = "\n\n".join(pages_text)
    metadata = _guess_metadata(full_text)
    metadata["num_pages"] = num_pages
    metadata["text"] = full_text
    return metadata


def _extract_pymupdf(pdf_path: str) -> dict:
    """Extract text using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text())
    doc.close()

    full_text = "\n\n".join(pages_text)
    metadata = _guess_metadata(full_text)
    metadata["num_pages"] = len(pages_text)
    metadata["text"] = full_text
    return metadata


def _guess_metadata(text: str) -> dict:
    """Heuristically extract title, authors, year from PDF text."""
    lines = [line.strip() for line in text.split("\n") if line.strip()][:20]
    title = lines[0] if lines else ""
    authors = ""
    year = None
    abstract = ""

    # Try to find year (4-digit number 19xx or 20xx)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text[:2000])
    if year_match:
        year = int(year_match.group(1))

    # Try to find authors (line with multiple commas or "and")
    for line in lines[1:5]:
        if "," in line and len(line) > 10 and not line[0].isdigit():
            authors = line
            break
        if " and " in line.lower() and len(line) > 10:
            authors = line
            break

    # Try to find abstract
    abstract_match = re.search(
        r"(?:abstract|resumen|summary)[:\s]*(.{100,1000})",
        text[:5000],
        re.IGNORECASE | re.DOTALL,
    )
    if abstract_match:
        abstract = abstract_match.group(1).strip()[:500]

    return {
        "title": title[:200],
        "authors": authors[:200],
        "year": year,
        "abstract": abstract,
    }


def ingest_pdf(pdf_path: str) -> dict:
    """Full pipeline: extract text from PDF → index in litdb.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.

    Returns
    -------
    dict
        Ingest result with success, filename, num_pages, num_tokens.
    """
    from .litdb import ingest_document

    extraction = extract_text_from_pdf(pdf_path)
    if extraction.get("error") and not extraction.get("text"):
        return {"success": False, "error": extraction["error"]}

    filename = os.path.basename(pdf_path)
    result = ingest_document(
        filename=filename,
        full_text=extraction["text"],
        title=extraction.get("title", ""),
        authors=extraction.get("authors", ""),
        year=extraction.get("year"),
        abstract=extraction.get("abstract", ""),
        num_pages=extraction.get("num_pages", 0),
    )
    return result


def ingest_text(text: str, filename: str = "pasted_text.txt") -> dict:
    """Index raw text (for non-PDF content like pasted abstracts).

    Also saves the text to the workspace so it appears in the Files panel.
    """
    from .litdb import ingest_document

    # Save to workspace for visibility in the Files panel
    _save_to_workspace(filename, text)

    metadata = _guess_metadata(text)
    return ingest_document(
        filename=filename,
        full_text=text,
        title=metadata.get("title", ""),
        authors=metadata.get("authors", ""),
        year=metadata.get("year"),
        abstract=metadata.get("abstract", ""),
    )


def _save_to_workspace(filename: str, text: str) -> str | None:
    """Save extracted text to /workspace/papers/ so it appears in Files panel."""
    workspace = os.environ.get("R_WORKSPACE_DIR", "/workspace")
    papers_dir = os.path.join(workspace, "papers")
    try:
        os.makedirs(papers_dir, exist_ok=True)
        # Save as .txt alongside the original filename
        safe_name = re.sub(r"[^\w\-.]", "_", filename)
        if not safe_name.endswith(".txt"):
            safe_name = os.path.splitext(safe_name)[0] + ".txt"
        out_path = os.path.join(papers_dir, safe_name)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("Saved paper text to workspace: %s", out_path)
        return out_path
    except OSError as exc:
        logger.warning("Could not save to workspace: %s", exc)
        return None


def ensure_upload_dir() -> str:
    """Create and return the upload directory path."""
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    return _UPLOAD_DIR
