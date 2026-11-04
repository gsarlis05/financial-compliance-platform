"""Antivirus scanning through a ClamAV daemon (clamd) over TCP, INSTREAM protocol (M2-4).

ClamAV runs as a separate service (GPL-2.0, never linked into the application). The scan fails
closed: if clamd is unreachable, slow or answers anything but "OK" or "FOUND", the upload is
refused (``ScanUnavailableError``), never accepted unscanned.
"""

import socket
import struct
from dataclasses import dataclass

from django.conf import settings

from fcp.core.errors import DomainError

CHUNK = 64 * 1024


class ScanUnavailableError(DomainError):
    code = "documents.scan_unavailable"
    status = 503
    title = "Virus scanning is unavailable"


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str = ""  # the virus name when not clean (safe to log: no document content)


def _receive(sock: socket.socket) -> bytes:
    reply = b""
    while not reply.endswith(b"\0"):
        part = sock.recv(4096)
        if not part:
            break
        reply += part
        if len(reply) > 4096:
            break
    return reply.rstrip(b"\0")


def scan(data: bytes) -> ScanResult:
    try:
        with socket.create_connection(
            (settings.CLAMD_HOST, settings.CLAMD_PORT), timeout=settings.CLAMD_TIMEOUT_SECONDS
        ) as sock:
            sock.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), CHUNK):
                chunk = data[start : start + CHUNK]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = _receive(sock).decode("utf-8", "replace")
    except OSError:
        raise ScanUnavailableError(
            "The file could not be checked for viruses right now, so it was not stored. "
            "Try again in a few minutes."
        ) from None
    if reply.endswith(" OK") or reply == "stream: OK":
        return ScanResult(clean=True)
    if reply.endswith(" FOUND"):
        signature = reply.removeprefix("stream:").removesuffix("FOUND").strip()
        return ScanResult(clean=False, signature=signature[:200])
    raise ScanUnavailableError("The virus scanner could not check this file, so it was not stored.")
