"""KDE Wayland ScreenCast portal capture with a bounded PipeWire reader.

The portal owns source selection.  This module never enumerates windows,
changes compositor policy, or captures before the desktop has approved a
ScreenCast request.  It deliberately exposes only the fixed portal methods
needed here and passes no configurable DBus service, path, or method names.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import select
import shutil
import subprocess
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum
from time import monotonic_ns
from typing import Any, Protocol, cast

import numpy as np

from geometry_dash_ai.capture.models import (
    MAX_CAPTURE_HEIGHT,
    MAX_CAPTURE_PIXELS,
    MAX_CAPTURE_WIDTH,
    CapturedFrame,
    CaptureRegion,
    RgbImage,
    validate_rate,
)
from geometry_dash_ai.capture.source import CaptureUnavailable
from geometry_dash_ai.portal_transport import (
    PortalTransport,
    PortalTransportError,
    PortalTransportTimeout,
    unwrap_portal_results,
    validate_object_path,
)

_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
_SESSION_IFACE = "org.freedesktop.portal.Session"
_SOURCE_MONITOR = 1
_SOURCE_WINDOW = 2
# The action watchdog has a 250 ms hard limit.  A capture read must fail well
# inside that period so the supervising worker can release input on a vanished
# PipeWire stream instead of waiting on a stalled pipe.
_MAX_CAPTURE_LATENCY_SECONDS = 0.2
_CAPS_PROBE_TIMEOUT_SECONDS = 5.0
_MAX_CAPS_DIAGNOSTIC_BYTES = 65_536
_CAPS_DIMENSIONS = re.compile(
    rb"video/x-raw[^\n]*?width=\(int\)([0-9]+),\s*height=\(int\)([0-9]+)"
)
_LOG = logging.getLogger(__name__)


class PortalResponseCode(IntEnum):
    """The documented response values used by xdg-desktop-portal requests."""

    SUCCESS = 0
    CANCELLED = 1
    DENIED = 2


class PortalDenied(CaptureUnavailable):
    """The user denied a portal request."""


class PortalCancelled(CaptureUnavailable):
    """The user cancelled a portal request."""


@dataclass(frozen=True, slots=True)
class PortalStream:
    """Validated metadata for exactly one user-selected PipeWire video node."""

    node_id: int
    # ``size`` is optional portal metadata in compositor coordinates.  It is
    # deliberately not used as the source of truth for PipeWire pixel buffers.
    width: int | None = None
    height: int | None = None
    source_type: int | None = None
    mapping_id: str | None = None
    pipewire_serial: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.node_id, bool) or not isinstance(self.node_id, int) or self.node_id < 0:
            raise ValueError("portal node id is invalid")
        if (self.width is None) != (self.height is None):
            raise ValueError("portal stream dimensions must both be known or both be unknown")
        if self.width is not None and self.height is not None and (
            isinstance(self.width, bool)
            or isinstance(self.height, bool)
            or not isinstance(self.width, int)
            or not isinstance(self.height, int)
            or not 1 <= self.width <= MAX_CAPTURE_WIDTH
            or not 1 <= self.height <= MAX_CAPTURE_HEIGHT
            or self.width * self.height > MAX_CAPTURE_PIXELS
        ):
            raise ValueError("portal stream dimensions exceed capture bounds")
        if self.source_type is not None and (
            isinstance(self.source_type, bool)
            or not isinstance(self.source_type, int)
            or self.source_type not in {_SOURCE_MONITOR, _SOURCE_WINDOW}
        ):
            raise ValueError("portal stream source type is invalid")
        if self.mapping_id is not None and (
            not isinstance(self.mapping_id, str)
            or len(self.mapping_id) > 512
            or any(not character.isprintable() for character in self.mapping_id)
        ):
            raise ValueError("portal stream mapping id is invalid")
        if self.pipewire_serial is not None and (
            isinstance(self.pipewire_serial, bool)
            or not isinstance(self.pipewire_serial, int)
            or not 0 <= self.pipewire_serial <= 2**64 - 1
        ):
            raise ValueError("portal PipeWire serial is invalid")

    @property
    def reported_width(self) -> int | None:
        """Return the optional compositor-coordinate width reported by the portal."""
        return self.width

    @property
    def reported_height(self) -> int | None:
        """Return the optional compositor-coordinate height reported by the portal."""
        return self.height


@dataclass(frozen=True, slots=True)
class PortalGrant:
    """One ephemeral, portal-authorized PipeWire connection."""

    remote_fd: int
    stream: PortalStream

    def __post_init__(self) -> None:
        if (
            isinstance(self.remote_fd, bool)
            or not isinstance(self.remote_fd, int)
            or self.remote_fd < 0
        ):
            raise ValueError("portal PipeWire descriptor is invalid")


def _unwrap(value: object) -> object:
    """Unwrap dbus-next variants without accepting arbitrary object behaviour."""
    variant_value = getattr(value, "value", None)
    return variant_value if variant_value is not None else value


def parse_portal_streams(value: object) -> PortalStream:
    """Parse one bounded ScreenCast stream from a portal response mapping."""
    unwrapped = _unwrap(value)
    if not isinstance(unwrapped, (list, tuple)) or len(unwrapped) != 1:
        raise CaptureUnavailable("portal must return exactly one selected source")
    item = unwrapped[0]
    if not isinstance(item, (list, tuple)) or len(item) != 2:
        raise CaptureUnavailable("portal returned malformed stream metadata")
    node_id, properties = item
    if isinstance(node_id, bool) or not isinstance(node_id, int):
        raise CaptureUnavailable("portal stream node id is invalid")
    properties = _unwrap(properties)
    if not isinstance(properties, Mapping):
        raise CaptureUnavailable("portal stream properties are invalid")
    size = _unwrap(properties.get("size"))
    if "size" not in properties:
        width: object = None
        height: object = None
    elif isinstance(size, (list, tuple)) and len(size) == 2:
        width, height = size
    else:
        raise CaptureUnavailable("portal stream dimensions are unsafe")
    try:
        return PortalStream(
            node_id,
            cast(int | None, width),
            cast(int | None, height),
            source_type=cast(int | None, _unwrap(properties.get("source_type"))),
            mapping_id=cast(str | None, _unwrap(properties.get("mapping_id"))),
            pipewire_serial=cast(int | None, _unwrap(properties.get("pipewire_serial"))),
        )
    except ValueError as exc:
        raise CaptureUnavailable("portal stream dimensions are unsafe") from exc


def parse_portal_response(code: object, results: object) -> Mapping[str, object]:
    """Validate a Response signal before any resource is used."""
    if isinstance(code, bool) or not isinstance(code, int):
        raise CaptureUnavailable("portal returned an invalid response code")
    if code == PortalResponseCode.CANCELLED:
        raise PortalCancelled("screen capture selection was cancelled")
    if code == PortalResponseCode.DENIED:
        raise PortalDenied("screen capture permission was denied")
    if code != PortalResponseCode.SUCCESS:
        raise CaptureUnavailable("portal returned an unsuccessful capture response")
    results = _unwrap(results)
    if not isinstance(results, Mapping):
        raise CaptureUnavailable("portal returned malformed response data")
    return {str(key): _unwrap(value) for key, value in results.items() if isinstance(key, str)}


class PortalCaptureClient(Protocol):
    """Small testable boundary around the fixed ScreenCast portal workflow."""

    def request_capture(self) -> PortalGrant: ...

    def close(self) -> None: ...


class KdeScreenCastPortal:
    """Synchronous owner for the current user's approved ScreenCast session."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        if not 1.0 <= timeout_seconds <= 120.0:
            raise ValueError("portal timeout must be within 1..120 seconds")
        self._timeout_seconds = timeout_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bus: Any | None = None
        self._transport: PortalTransport | None = None
        self._session_path: str | None = None
        self._closed = False

    def request_capture(self) -> PortalGrant:
        if self._closed:
            raise CaptureUnavailable("portal capture session is closed")
        if shutil.which("gst-launch-1.0") is None:
            raise CaptureUnavailable(
                "GStreamer is unavailable; cannot consume approved PipeWire video"
            )
        try:
            from dbus_next import BusType, Variant
            from dbus_next.aio import MessageBus
        except ImportError as exc:
            raise CaptureUnavailable(
                "Wayland portal support needs the optional pure-Python 'dbus-next' live dependency"
            ) from exc
        self._loop = asyncio.new_event_loop()
        try:
            return self._loop.run_until_complete(self._request_async(MessageBus, BusType, Variant))
        except (PortalCancelled, PortalDenied, CaptureUnavailable):
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise CaptureUnavailable(
                "could not connect to the user ScreenCast portal; "
                "confirm an active KDE Wayland session"
            ) from exc

    async def _request_async(self, message_bus: Any, bus_type: Any, variant: Any) -> PortalGrant:
        self._bus = await message_bus(bus_type=bus_type.SESSION, negotiate_unix_fd=True).connect()
        try:
            if self._loop is None:
                raise CaptureUnavailable("ScreenCast portal event loop was not initialized")
            self._transport = PortalTransport(self._bus, self._loop, self._timeout_seconds)
            created = await self._transport.screencast_create_session(
                {
                    "handle_token": variant("s", "geometry_dash_capture"),
                    "session_handle_token": variant("s", "geometry_dash_session"),
                }
            )
            session = parse_portal_response(
                created.code, unwrap_portal_results(created)
            ).get("session_handle")
            self._session_path = validate_object_path(session, description="ScreenCast session")
            selected = await self._transport.screencast_select_sources(
                self._session_path,
                {
                    "handle_token": variant("s", "geometry_dash_sources"),
                    "types": variant("u", _SOURCE_MONITOR | _SOURCE_WINDOW),
                    "multiple": variant("b", False),
                    "cursor_mode": variant("u", 1),
                },
            )
            parse_portal_response(selected.code, unwrap_portal_results(selected))
            started = await self._transport.screencast_start(
                self._session_path,
                {"handle_token": variant("s", "geometry_dash_start")},
            )
            start_results = parse_portal_response(started.code, unwrap_portal_results(started))
            stream = parse_portal_streams(start_results.get("streams"))
            remote_fd = await self._transport.open_pipewire_remote(self._session_path)
            return PortalGrant(remote_fd, stream)
        except PortalTransportTimeout as exc:
            raise CaptureUnavailable("ScreenCast portal response timed out") from exc
        except PortalTransportError as exc:
            raise CaptureUnavailable(f"ScreenCast portal transport failed: {exc}") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if (
            self._loop is not None
            and self._transport is not None
            and self._session_path is not None
        ):
            with suppress(Exception):
                self._loop.run_until_complete(self._close_session())
        if self._bus is not None:
            self._bus.disconnect()
        if self._loop is not None:
            self._loop.close()
        self._session_path = None
        self._transport = None
        self._bus = None
        self._loop = None

    async def _close_session(self) -> None:
        if self._transport is None or self._session_path is None:
            return
        await self._transport.close_session(self._session_path)


class PipeWirePortalFrameSource:
    """Latest-frame ScreenCast source using one portal-selected PipeWire stream.

    GStreamer is launched with a fixed argument vector and inherited portal FD;
    there is no shell, command interpolation, network use, or input API.  The
    crop is performed by the fixed local GStreamer pipeline, so a larger
    selected monitor surface never enters a Python frame buffer.
    """

    def __init__(
        self,
        region: CaptureRegion | None,
        target_fps: float = 60.0,
        portal: PortalCaptureClient | None = None,
    ) -> None:
        self._requested_region = region
        self._target_fps = validate_rate(target_fps)
        self._portal = portal or KdeScreenCastPortal()
        self._timestamps: deque[int] = deque(maxlen=120)
        self._latencies: deque[float] = deque(maxlen=120)
        self._sequence = 0
        self._dropped = 0
        self._closed = False
        self._process: subprocess.Popen[bytes] | None = None
        self._remote_fd: int | None = None
        try:
            grant = self._portal.request_capture()
            self._remote_fd = grant.remote_fd
            self._stream = grant.stream
            source_width, source_height = self._probe_source_dimensions(grant)
            self._region = region or CaptureRegion(0, 0, source_width, source_height)
            self._validate_crop(source_width, source_height)
            self._frame_bytes = self._region.width * self._region.height * 3
            self._process = self._start_gstreamer(grant, source_width, source_height)
        except Exception:
            self.close()
            raise

    @property
    def region(self) -> CaptureRegion:
        return self._region

    @property
    def dropped_frames(self) -> int:
        return self._dropped

    @property
    def capture_fps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        return 0.0 if elapsed <= 0 else (len(self._timestamps) - 1) * 1_000_000_000.0 / elapsed

    @property
    def capture_latency_ms(self) -> float:
        return 0.0 if not self._latencies else sum(self._latencies) / len(self._latencies)

    @property
    def maximum_recent_capture_latency_ms(self) -> float:
        return 0.0 if not self._latencies else max(self._latencies)

    def _validate_crop(self, source_width: int, source_height: int) -> None:
        if self._region.left < 0 or self._region.top < 0:
            raise CaptureUnavailable(
                "portal crop origin must be non-negative within the selected source"
            )
        if self._region.left + self._region.width > source_width or (
            self._region.top + self._region.height > source_height
        ):
            raise CaptureUnavailable(
                "configured capture crop "
                f"{self._region.width}x{self._region.height} exceeds selected source "
                f"{source_width}x{source_height}"
            )

    def _probe_source_dimensions(self, grant: PortalGrant) -> tuple[int, int]:
        """Read bounded negotiated raw-video caps from the approved PipeWire node.

        The ScreenCast ``size`` property is optional and uses compositor
        coordinates, so it cannot safely size a raw PipeWire buffer.  A short,
        fixed GStreamer probe obtains the source caps before the crop reader is
        constructed.  It reuses the same approved portal FD and never retains
        video frames or portal response data.
        """
        if grant.stream.reported_width is None:
            _LOG.debug("Portal stream metadata omitted size; probing PipeWire caps")
        command = [
            "gst-launch-1.0",
            "-v",
            "pipewiresrc",
            f"fd={grant.remote_fd}",
            f"path={grant.stream.node_id}",
            "!",
            "queue",
            "max-size-buffers=1",
            "max-size-bytes=0",
            "max-size-time=0",
            "leaky=downstream",
            "!",
            "videoconvert",
            "!",
            "video/x-raw,format=RGB",
            "!",
            "fakesink",
            "sync=false",
        ]
        try:
            probe = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
                pass_fds=(grant.remote_fd,),
            )
        except OSError as exc:
            raise CaptureUnavailable("could not start local PipeWire caps probe") from exc
        try:
            dimensions = self._read_negotiated_dimensions(probe)
        finally:
            self._stop_process(probe)
        _LOG.debug("PipeWire negotiated source size: %dx%d", *dimensions)
        return dimensions

    @staticmethod
    def _read_negotiated_dimensions(process: subprocess.Popen[bytes]) -> tuple[int, int]:
        if process.stderr is None:
            raise CaptureUnavailable("PipeWire caps probe has no diagnostic stream")
        diagnostic = bytearray()
        deadline_ns = monotonic_ns() + int(_CAPS_PROBE_TIMEOUT_SECONDS * 1_000_000_000.0)
        while monotonic_ns() < deadline_ns and len(diagnostic) < _MAX_CAPS_DIAGNOSTIC_BYTES:
            dimensions = _parse_pipewire_caps(diagnostic)
            if dimensions is not None:
                return dimensions
            if process.poll() is not None:
                break
            remaining = (deadline_ns - monotonic_ns()) / 1_000_000_000.0
            ready, _, _ = select.select([process.stderr], [], [], max(0.0, remaining))
            if not ready:
                break
            maximum_read = min(4_096, _MAX_CAPS_DIAGNOSTIC_BYTES - len(diagnostic))
            chunk = os.read(process.stderr.fileno(), maximum_read)
            if not chunk:
                break
            diagnostic.extend(chunk)
        dimensions = _parse_pipewire_caps(diagnostic)
        if dimensions is not None:
            return dimensions
        raise CaptureUnavailable("PipeWire stream did not negotiate video dimensions")

    def _start_gstreamer(
        self, grant: PortalGrant, source_width: int, source_height: int
    ) -> subprocess.Popen[bytes]:
        command = [
            "gst-launch-1.0",
            "-q",
            "pipewiresrc",
            f"fd={grant.remote_fd}",
            f"path={grant.stream.node_id}",
            "!",
            "queue",
            "max-size-buffers=1",
            "max-size-bytes=0",
            "max-size-time=0",
            "leaky=downstream",
            "!",
            "videoconvert",
            "!",
            "videocrop",
            f"left={self._region.left}",
            f"top={self._region.top}",
            f"right={source_width - self._region.left - self._region.width}",
            f"bottom={source_height - self._region.top - self._region.height}",
            "!",
            (
                "video/x-raw,format=RGB,"
                f"width={self._region.width},height={self._region.height}"
            ),
            "!",
            "fdsink",
            "fd=1",
        ]
        try:
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                pass_fds=(grant.remote_fd,),
            )
        except OSError as exc:
            raise CaptureUnavailable("could not start local PipeWire frame reader") from exc

    def capture_once(self) -> CapturedFrame:
        if self._closed or self._process is None or self._process.stdout is None:
            raise CaptureUnavailable("portal capture source is closed")
        started = monotonic_ns()
        raw = self._read_exact(self._frame_bytes)
        image: RgbImage = np.ascontiguousarray(
            np.frombuffer(raw, dtype=np.uint8).reshape(
                self._region.height,
                self._region.width,
                3,
            )
        )
        timestamp = monotonic_ns()
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise CaptureUnavailable("portal frame timestamps are not monotonic")
        if self._timestamps:
            elapsed = (timestamp - self._timestamps[-1]) / 1_000_000_000.0
            self._dropped += max(0, round(elapsed * self._target_fps) - 1)
        frame = CapturedFrame(image, timestamp, self._sequence, self._region)
        self._sequence += 1
        self._timestamps.append(timestamp)
        self._latencies.append((timestamp - started) / 1_000_000.0)
        return frame

    def _read_exact(self, size: int) -> bytes:
        if self._process is None or self._process.stdout is None:
            raise CaptureUnavailable("PipeWire reader is unavailable")
        buffer = bytearray()
        remaining = size
        deadline_ns = monotonic_ns() + int(_MAX_CAPTURE_LATENCY_SECONDS * 1_000_000_000.0)
        while remaining:
            if self._process.poll() is not None:
                raise CaptureUnavailable("portal PipeWire stream ended")
            remaining_seconds = (deadline_ns - monotonic_ns()) / 1_000_000_000.0
            if remaining_seconds <= 0.0:
                raise CaptureUnavailable("portal PipeWire frame read timed out")
            ready, _, _ = select.select(
                [self._process.stdout], [], [], remaining_seconds
            )
            if not ready:
                raise CaptureUnavailable("portal PipeWire frame read timed out")
            chunk = os.read(self._process.stdout.fileno(), remaining)
            if not chunk:
                raise CaptureUnavailable("portal PipeWire stream ended")
            buffer.extend(chunk)
            remaining -= len(chunk)
        return bytes(buffer)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        self._process = None
        if process is not None:
            self._stop_process(process)
        if self._remote_fd is not None:
            with suppress(OSError):
                os.close(self._remote_fd)
            self._remote_fd = None
        with suppress(Exception):
            self._portal.close()

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        with suppress(OSError):
            process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            with suppress(OSError):
                process.kill()
            with suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=2.0)
        if process.stdout is not None:
            with suppress(OSError):
                process.stdout.close()
        if process.stderr is not None:
            with suppress(OSError):
                process.stderr.close()


def _validated_pipewire_dimensions(width_bytes: bytes, height_bytes: bytes) -> tuple[int, int]:
    """Validate dimensions parsed from bounded, fixed GStreamer diagnostics."""
    try:
        width = int(width_bytes)
        height = int(height_bytes)
        PortalStream(0, width, height)
    except (TypeError, ValueError) as exc:
        raise CaptureUnavailable("PipeWire negotiated unsafe video dimensions") from exc
    return width, height


def _parse_pipewire_caps(diagnostic: bytes | bytearray) -> tuple[int, int] | None:
    """Extract bounded raw-video dimensions from fixed GStreamer ``-v`` output."""
    match = _CAPS_DIMENSIONS.search(diagnostic)
    if match is None:
        return None
    return _validated_pipewire_dimensions(match.group(1), match.group(2))
