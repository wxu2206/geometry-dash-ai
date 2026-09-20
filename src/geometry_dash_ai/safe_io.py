"""Small owner-only atomic write primitive for fixed, validated local paths."""

from __future__ import annotations

import os
import secrets
from contextlib import suppress
from pathlib import Path


def atomic_owner_write(destination: Path, payload: bytes) -> None:
    """Atomically replace ``destination`` after a complete owner-only write.

    Callers validate their fixed parent path and symlink policy before entering
    this helper. A failed write leaves an existing configuration or calibration
    file intact and removes the same-directory temporary file.
    """
    if not isinstance(payload, bytes):
        raise TypeError("atomic local payload must be bytes")
    temporary = destination.parent / f".{destination.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    replaced = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("atomic local write did not complete")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, destination)
        replaced = True
        os.chmod(destination, 0o600)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not replaced:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
