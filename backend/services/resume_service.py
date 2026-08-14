"""Turn an uploaded resume into text.

The file itself is never stored. Only the extracted text reaches the database,
which keeps a document full of a home address and a phone number out of blob
storage for no benefit -- the profile only ever needed the words.

Type is decided by magic bytes rather than by the filename or the client's
declared content type, both of which are the caller's claim about the file
rather than evidence about it.
"""

from __future__ import annotations

import io
import logging

import docx
from fastapi import HTTPException, status
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# 5 MB. Enforced against the bytes actually read, not a declared length.
MAX_BYTES = 5 * 1024 * 1024

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"


def extract_text(filename: str, data: bytes) -> str:
    """The text of one uploaded resume, or an HTTPException naming the refusal."""
    if len(data) >= MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Resume must be under 5 MB",
        )
    name = filename.lower().strip()
    if name.endswith(".doc"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Legacy .doc is not supported. Save as PDF or .docx and try again",
        )
    if data.startswith(_PDF_MAGIC):
        return _from_pdf(data)
    if data.startswith(_ZIP_MAGIC):
        return _from_docx(data)
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Upload a PDF or a .docx file",
    )


def _from_pdf(data: bytes) -> str:
    """The text of a PDF, or a 422 when the bytes cannot be parsed."""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 -- a corrupt file is the caller's problem
        logger.info("resume pdf unreadable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That PDF could not be read",
        ) from exc


def _from_docx(data: bytes) -> str:
    """The text of a .docx, or a 422 when the container cannot be parsed."""
    try:
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs).strip()
    except Exception as exc:  # noqa: BLE001 -- a corrupt file is the caller's problem
        logger.info("resume docx unreadable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That Word file could not be read",
        ) from exc
