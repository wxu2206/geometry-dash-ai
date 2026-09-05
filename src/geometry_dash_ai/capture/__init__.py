"""Observe-only, bounded live-screen capture interfaces."""

from geometry_dash_ai.capture.models import CapturedFrame, CaptureRegion, validate_image
from geometry_dash_ai.capture.mss_source import MssFrameSource
from geometry_dash_ai.capture.portal import (
    KdeScreenCastPortal,
    PipeWirePortalFrameSource,
    PortalCancelled,
    PortalDenied,
    PortalGrant,
    PortalStream,
    parse_portal_response,
    parse_portal_streams,
)
from geometry_dash_ai.capture.source import (
    BufferMetrics,
    CaptureUnavailable,
    FrameSource,
    LatestFrameBuffer,
)
from geometry_dash_ai.capture.synthetic import SyntheticFrameSource

__all__ = [
    "BufferMetrics",
    "CapturedFrame",
    "CaptureRegion",
    "CaptureUnavailable",
    "FrameSource",
    "LatestFrameBuffer",
    "MssFrameSource",
    "KdeScreenCastPortal",
    "PipeWirePortalFrameSource",
    "PortalCancelled",
    "PortalDenied",
    "PortalGrant",
    "PortalStream",
    "SyntheticFrameSource",
    "validate_image",
    "parse_portal_response",
    "parse_portal_streams",
]
