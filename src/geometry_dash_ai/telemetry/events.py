"""Versioned JSON Lines telemetry primitives."""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO, cast

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    event: str
    monotonic_ns: int
    payload: Mapping[str, Any]
    wall_time: str | None = None
    schema_version: int = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        wall_time = self.wall_time or datetime.now(UTC).isoformat()
        return {
            "schema_version": self.schema_version,
            "event": self.event,
            "wall_time": wall_time,
            "monotonic_ns": self.monotonic_ns,
            "payload": dict(self.payload),
        }


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    raise TypeError(f"cannot serialize {type(value).__name__}")


class JsonlTelemetryWriter:
    """Append versioned events to plain or gzip-compressed JSON Lines."""

    def __init__(self, path: Path, *, compress: bool | None = None) -> None:
        self.path = path
        self.compress = path.suffix == ".gz" if compress is None else compress
        self._stream: TextIO | None = None

    def __enter__(self) -> JsonlTelemetryWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.compress:
            self._stream = gzip.open(self.path, mode="at", encoding="utf-8")
        else:
            self._stream = self.path.open(mode="a", encoding="utf-8")
        return self

    def write(self, event: TelemetryEvent) -> None:
        if self._stream is None:
            raise RuntimeError("telemetry writer must be used as a context manager")
        json.dump(event.as_dict(), self._stream, default=_json_default, separators=(",", ":"))
        self._stream.write("\n")
        self._stream.flush()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
