from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import numpy as np

from geometry_dash_ai.capture import (
    CaptureRegion,
    CaptureUnavailable,
    PipeWirePortalFrameSource,
    PortalCancelled,
    PortalDenied,
    PortalGrant,
    PortalStream,
    parse_portal_response,
    parse_portal_streams,
)


class _FakePortal:
    def __init__(self, grant: PortalGrant) -> None:
        self.grant = grant
        self.closed = False

    def request_capture(self) -> PortalGrant:
        return self.grant

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, read_fd: int, *, ended: bool = False) -> None:
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.stderr = None
        self._ended = ended
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 1 if self._ended else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


class _TestPortalSource(PipeWirePortalFrameSource):
    def __init__(self, *args: object, process: _FakeProcess, **kwargs: object) -> None:
        self._test_process = process
        super().__init__(*args, **kwargs)

    def _start_gstreamer(self, grant: PortalGrant) -> _FakeProcess:
        return self._test_process


def _grant(width: int = 4, height: int = 3) -> tuple[PortalGrant, int]:
    remote_fd, unused = os.pipe()
    os.close(unused)
    return PortalGrant(remote_fd, PortalStream(7, width, height)), remote_fd


class PortalCaptureTests(unittest.TestCase):
    def test_portal_response_distinguishes_denial_cancellation_and_bad_data(self) -> None:
        with self.assertRaises(PortalDenied):
            parse_portal_response(2, {})
        with self.assertRaises(PortalCancelled):
            parse_portal_response(1, {})
        with self.assertRaisesRegex(CaptureUnavailable, "invalid response"):
            parse_portal_response("0", {})
        with self.assertRaisesRegex(CaptureUnavailable, "malformed"):
            parse_portal_response(0, [])

    def test_stream_parser_rejects_malformed_and_oversized_metadata(self) -> None:
        with self.assertRaisesRegex(CaptureUnavailable, "exactly one"):
            parse_portal_streams([])
        with self.assertRaisesRegex(CaptureUnavailable, "unsafe"):
            parse_portal_streams([(3, {"size": (8_000, 1)})])

    def test_live_adapter_crops_the_approved_source_and_releases_resources(self) -> None:
        grant, remote_fd = _grant()
        data_read, data_write = os.pipe()
        raw = np.arange(4 * 3 * 3, dtype=np.uint8).tobytes()
        os.write(data_write, raw)
        os.close(data_write)
        portal = _FakePortal(grant)
        process = _FakeProcess(data_read)
        source = _TestPortalSource(CaptureRegion(1, 1, 2, 2), portal=portal, process=process)
        result = source.capture_once()
        np.testing.assert_array_equal(
            result.image,
            np.arange(4 * 3 * 3, dtype=np.uint8).reshape(3, 4, 3)[1:3, 1:3],
        )
        source.close()
        self.assertTrue(portal.closed)
        self.assertTrue(process.terminated)
        with self.assertRaises(OSError):
            os.fstat(remote_fd)

    def test_source_loss_and_invalid_crop_fail_cleanly(self) -> None:
        grant, _ = _grant()
        data_read, data_write = os.pipe()
        os.close(data_write)
        portal = _FakePortal(grant)
        source = _TestPortalSource(
            CaptureRegion(0, 0, 4, 3), portal=portal, process=_FakeProcess(data_read, ended=True)
        )
        with self.assertRaisesRegex(CaptureUnavailable, "stream ended"):
            source.capture_once()
        source.close()
        invalid_grant, _ = _grant()
        data_read, data_write = os.pipe()
        os.close(data_write)
        with self.assertRaisesRegex(CaptureUnavailable, "crop exceeds"):
            _TestPortalSource(
                CaptureRegion(3, 0, 2, 2),
                portal=_FakePortal(invalid_grant),
                process=_FakeProcess(data_read),
            )

    def test_repeated_portal_timestamp_is_rejected(self) -> None:
        grant, _ = _grant()
        data_read, data_write = os.pipe()
        raw = bytes(4 * 3 * 3)
        os.write(data_write, raw + raw)
        os.close(data_write)
        source = _TestPortalSource(
            CaptureRegion(0, 0, 4, 3), portal=_FakePortal(grant), process=_FakeProcess(data_read)
        )
        with patch("geometry_dash_ai.capture.portal.monotonic_ns", side_effect=(10, 11, 10, 11)):
            source.capture_once()
            with self.assertRaisesRegex(CaptureUnavailable, "not monotonic"):
                source.capture_once()
        source.close()
