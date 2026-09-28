"""Shared upload validation for M1 document and M2 voice-incident uploads.

Both endpoints read the whole file into memory (no streaming-to-disk
path exists), so a size cap is a real denial-of-service control, not a
formality. Content-type is checked against an explicit allowlist rather
than trusted blindly from the client - a client can lie about
Content-Type, so this is a defence-in-depth check, not the only one:
run_ocr() already fails closed (empty text, 0 confidence -> fallback) on
an unreadable image rather than crashing, and the same discipline is
kept here rather than trying to sniff magic bytes for every format.

Neither upload is ever written to a filesystem path derived from the
client-supplied filename - only a SHA-256 hash of the content is
persisted - so path traversal via a malicious filename is not a
reachable code path in this project, and no filename-sanitization
function is a substitute for that: the actual mitigation is "we never
build a path from client input", verified by grep during this audit.
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile


class UploadTooLarge(HTTPException):
    def __init__(self, limit_bytes: int):
        super().__init__(
            status_code=413,
            detail=f"Upload exceeds the maximum accepted size of {limit_bytes} bytes.",
        )


class UnsupportedUploadType(HTTPException):
    def __init__(self, content_type: str | None, allowed: tuple[str, ...]):
        super().__init__(
            status_code=415,
            detail=f"Unsupported content type {content_type!r}; allowed: {sorted(allowed)}.",
        )


async def read_validated_upload(
    file: UploadFile, *, max_bytes: int, allowed_content_types: tuple[str, ...],
) -> bytes:
    """Enforces content-type allowlist, then a hard size cap while
    reading - a client can send an honest Content-Type header and still
    stream more bytes than declared, so the cap is enforced on what is
    actually read, not merely checked against a trusted length header."""
    if file.content_type not in allowed_content_types:
        raise UnsupportedUploadType(file.content_type, allowed_content_types)

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLarge(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
