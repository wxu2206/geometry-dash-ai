from __future__ import annotations

import os
import subprocess
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
from geometry_dash_ai.capture.portal import _parse_pipewire_caps


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

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float) -> int:
        return 0


class _StubbornProcess:
    stdout = None
    stderr = None

    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float) -> int:
        del timeout
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired("gst-launch-1.0", 2.0)
        return 0


class _TestPortalSource(PipeWirePortalFrameSource):
    def __init__(self, *args: object, process: _FakeProcess, **kwargs: object) -> None:
        self._test_process = process
        super().__init__(*args, **kwargs)

    def _probe_source_dimensions(self, grant: PortalGrant) -> tuple[int, int]:
        width = grant.stream.reported_width
        height = grant.stream.reported_height
        if width is None or height is None:
            return 4, 3
        return width, height

    def _start_gstreamer(
        self, grant: PortalGrant, source_width: int, source_height: int
    ) -> _FakeProcess:
        del grant, source_width, source_height
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
        with self.assertRaisesRegex(CaptureUnavailable, "unsafe"):
            parse_portal_streams([(3, {"size": (-1, 1)})])
        with self.assertRaisesRegex(CaptureUnavailable, "unsafe"):
            parse_portal_streams([(3, {"size": "not-a-size"})])

    def test_stream_parser_accepts_missing_optional_size_and_source_metadata(self) -> None:
        window = parse_portal_streams(
            [(3, {"source_type": 2, "mapping_id": "window-1", "pipewire_serial": 9})]
        )
        self.assertEqual(window.node_id, 3)
        self.assertIsNone(window.reported_width)
        self.assertIsNone(window.reported_height)
        self.assertEqual(window.source_type, 2)
        self.assertEqual(window.mapping_id, "window-1")
        self.assertEqual(window.pipewire_serial, 9)
        monitor = parse_portal_streams([(4, {"source_type": 1, "size": (4, 3)})])
        self.assertEqual((monitor.reported_width, monitor.reported_height), (4, 3))

    def test_unknown_portal_size_is_safely_sized_from_pipewire_before_crop(self) -> None:
        remote_fd, unused = os.pipe()
        os.close(unused)
        grant = PortalGrant(remote_fd, PortalStream(7))
        data_read, data_write = os.pipe()
        expected = np.arange(2 * 2 * 3, dtype=np.uint8).reshape(2, 2, 3)
        os.write(data_write, expected.tobytes())
        os.close(data_write)
        source = _TestPortalSource(
            CaptureRegion(1, 1, 2, 2),
            portal=_FakePortal(grant),
            process=_FakeProcess(data_read),
        )
        self.assertEqual(source.region, CaptureRegion(1, 1, 2, 2))
        np.testing.assert_array_equal(source.capture_once().image, expected)
        source.close()

    def test_caps_dimensions_are_validated_independently_of_portal_metadata(self) -> None:
        renderings = (
            (
                b"GstPad:src: caps = video/x-raw, width=(int)1152, height=(int)648, "
                b"format=(string)RGB",
                (1152, 648),
            ),
            (
                b"GstPad:src: caps = video/x-raw, height = (int) 1080, "
                b"colorimetry=(string)sRGB, width = (int) 1920",
                (1920, 1080),
            ),
            (
                b"GstPad:src: caps = video/x-raw(memory:DMABuf),\n"
                b"  format=(string)RGB,\n  width=(guint)2560,\n  height=(gint)1440",
                (2560, 1440),
            ),
        )
        for caps, expected in renderings:
            with self.subTest(caps=caps):
                self.assertEqual(_parse_pipewire_caps(caps), expected)
        self.assertIsNone(_parse_pipewire_caps(b"video/x-raw, format=(string)RGB"))
        self.assertIsNone(
            _parse_pipewire_caps(
                b"first caps = video/x-raw, width=(int)320\n"
                b"second caps = video/x-raw, height=(int)240"
            )
        )

    def test_caps_parser_corpus_keeps_dimensions_within_one_video_record(self) -> None:
        corpus = (
            (
                b"caps=video/x-raw,format=(string)RGB,framerate=(fraction)60/1,"
                b"width=(guint)1280,height=(gint)720,pixel-aspect-ratio=(fraction)1/1",
                (1280, 720),
            ),
            (
                b"pad caps = video/x-raw(memory:DMABuf), colorimetry=(string)sRGB,\n"
                b" interlace-mode=(string)progressive, height=(int)1080, width=(int)1920",
                (1920, 1080),
            ),
            (
                b"unrelated caps = audio/x-raw,rate=(int)48000\n"
                b"video caps = video/x-raw, width=(int)800, height=(int)600, format=(string)RGB",
                (800, 600),
            ),
            (
                b"first caps = video/x-raw,width=(int)640,height=(int)480\n"
                b"second caps = video/x-raw,width=(int)1280,height=(int)720",
                (640, 480),
            ),
        )
        for diagnostic, expected in corpus:
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(_parse_pipewire_caps(diagnostic), expected)

    def test_caps_probe_drains_final_output_after_the_process_has_exited(self) -> None:
        read_fd, write_fd = os.pipe()
        os.write(
            write_fd,
            b"GstPad:src: caps = video/x-raw, format=(string)RGB, "
            b"width=(int)320, height=(int)180\n",
        )
        os.close(write_fd)
        process = _FakeProcess(read_fd, ended=True)
        try:
            self.assertEqual(
                PipeWirePortalFrameSource._read_negotiated_dimensions(process),
                (320, 180),
            )
        finally:
            process.stdout.close()

    def test_process_cleanup_escalates_to_kill_when_terminate_is_ignored(self) -> None:
        process = _StubbornProcess()
        PipeWirePortalFrameSource._stop_process(process)  # type: ignore[arg-type]
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.wait_calls, 2)

    def test_live_adapter_crops_the_approved_source_and_releases_resources(self) -> None:
        grant, remote_fd = _grant()
        data_read, data_write = os.pipe()
        expected = np.arange(2 * 2 * 3, dtype=np.uint8).reshape(2, 2, 3)
        raw = expected.tobytes()
        os.write(data_write, raw)
        os.close(data_write)
        portal = _FakePortal(grant)
        process = _FakeProcess(data_read)
        source = _TestPortalSource(CaptureRegion(1, 1, 2, 2), portal=portal, process=process)
        result = source.capture_once()
        np.testing.assert_array_equal(result.image, expected)
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
        with self.assertRaisesRegex(CaptureUnavailable, "exceeds selected source 4x3"):
            _TestPortalSource(
                CaptureRegion(3, 0, 2, 2),
                portal=_FakePortal(invalid_grant),
                process=_FakeProcess(data_read),
            )

    def test_stalled_stream_fails_without_waiting_for_an_unbounded_read(self) -> None:
        grant, _ = _grant()
        data_read, data_write = os.pipe()
        portal = _FakePortal(grant)
        source = _TestPortalSource(
            CaptureRegion(0, 0, 4, 3), portal=portal, process=_FakeProcess(data_read)
        )
        with (
            patch("geometry_dash_ai.capture.portal.select.select", return_value=([], [], [])),
            self.assertRaisesRegex(CaptureUnavailable, "read timed out"),
        ):
            source.capture_once()
        os.close(data_write)
        source.close()
        self.assertTrue(portal.closed)

    def test_repeated_portal_timestamp_is_rejected(self) -> None:
        grant, _ = _grant()
        data_read, data_write = os.pipe()
        raw = bytes(4 * 3 * 3)
        os.write(data_write, raw + raw)
        os.close(data_write)
        source = _TestPortalSource(
            CaptureRegion(0, 0, 4, 3), portal=_FakePortal(grant), process=_FakeProcess(data_read)
        )
        with patch(
            "geometry_dash_ai.capture.portal.monotonic_ns",
            side_effect=(10, 11, 10, 11, 10, 11, 10, 11),
        ):
            source.capture_once()
            with self.assertRaisesRegex(CaptureUnavailable, "not monotonic"):
                source.capture_once()
        source.close()
