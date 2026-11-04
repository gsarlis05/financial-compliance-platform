"""What a file really is, from its bytes, compared with its extension (M2-4, AC-M2-4).

Only an allowlist of document types is accepted. The stored content type always comes from this
module, never from the browser, and downloads are served with ``nosniff``.
"""

import io
import re
import unicodedata
import zipfile

from fcp.core.errors import ValidationFailedError

# extension -> (kind sniffed from the content, content type served)
ALLOWED: dict[str, tuple[str, str]] = {
    "pdf": ("pdf", "application/pdf"),
    "png": ("png", "image/png"),
    "jpg": ("jpeg", "image/jpeg"),
    "jpeg": ("jpeg", "image/jpeg"),
    "xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": ("text", "text/csv"),
    "txt": ("text", "text/plain"),
    "xml": ("xml", "application/xml"),
}
_TEXT_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DocumentTypeError(ValidationFailedError):
    code = "documents.type_mismatch"
    title = "The file type is not accepted"


def _zip_kind(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist()[:2000])  # names only: nothing is extracted
    except (zipfile.BadZipFile, ValueError, OSError):
        return "unknown"
    if "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names):
        return "xlsx"
    return "zip"


def _text_kind(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "unknown"
    if _TEXT_CONTROLS.search(text):
        return "unknown"
    return "xml" if text.lstrip().startswith("<") else "text"


def sniff(data: bytes) -> str:
    """The kind of content: pdf, png, jpeg, xlsx, zip, xml, text or unknown."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    return _text_kind(data)


def safe_filename(name: str) -> str:
    """The last path component, without control or separator characters, at most 200 chars."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(
        c
        for c in unicodedata.normalize("NFC", base)
        if unicodedata.category(c)[0] != "C" and c not in '<>:"|?*'
    )
    base = base.strip(" .") or "document"
    if len(base) > 200:
        stem, dot, ext = base.rpartition(".")
        base = f"{stem[: 199 - len(ext)]}.{ext}" if dot and len(ext) <= 10 else base[:200]
    return base


def check(filename: str, data: bytes) -> str:
    """The content type to store, or ``DocumentTypeError`` if the type is not allowed or the
    content does not match the extension."""
    extension = filename.rpartition(".")[2].lower() if "." in filename else ""
    if extension not in ALLOWED:
        allowed = ", ".join(f".{e}" for e in ALLOWED)
        raise DocumentTypeError(
            f"Only these file types are accepted: {allowed}.",
            field_errors={"file": ["type not allowed"]},
        )
    expected, content_type = ALLOWED[extension]
    actual = sniff(data)
    if actual != expected:
        raise DocumentTypeError(
            f"The file is named .{extension} but its content is "
            f"{'not a recognised document' if actual == 'unknown' else actual}. Upload the "
            "original file.",
            field_errors={"file": ["content does not match the extension"]},
        )
    return content_type
