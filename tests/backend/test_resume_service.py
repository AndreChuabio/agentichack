import io
import zipfile

import pytest
from fastapi import HTTPException

from backend.services import resume_service


def _minimal_docx() -> bytes:
    """A DOCX is a zip; magic-byte detection only needs the container."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def test_oversized_upload_is_413():
    with pytest.raises(HTTPException) as exc:
        resume_service.extract_text("cv.pdf", b"%PDF" + b"x" * resume_service.MAX_BYTES)
    assert exc.value.status_code == 413


def test_legacy_doc_is_refused():
    with pytest.raises(HTTPException) as exc:
        resume_service.extract_text("cv.doc", b"\xd0\xcf\x11\xe0")
    assert exc.value.status_code == 415


def test_a_pdf_extension_with_wrong_magic_bytes_is_refused():
    """The filename is the client's claim; the bytes are the evidence."""
    with pytest.raises(HTTPException) as exc:
        resume_service.extract_text("cv.pdf", b"not a pdf at all")
    assert exc.value.status_code == 415


def test_a_docx_extension_with_wrong_magic_bytes_is_refused():
    with pytest.raises(HTTPException) as exc:
        resume_service.extract_text("cv.docx", b"not a zip")
    assert exc.value.status_code == 415


def test_a_real_docx_container_is_accepted():
    # Empty document, so the text is empty -- what matters is that it parses
    # rather than being refused as the wrong type.
    try:
        resume_service.extract_text("cv.docx", _minimal_docx())
    except HTTPException as exc:
        assert exc.status_code == 422, "a valid container must not be a type refusal"
