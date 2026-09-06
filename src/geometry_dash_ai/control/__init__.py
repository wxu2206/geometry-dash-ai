"""Safe, replaceable input-control backends."""

from geometry_dash_ai.control.backend import (
    ActionBackend,
    ControlPermissionDenied,
    ControlPermissionLost,
    ControlUnavailable,
)
from geometry_dash_ai.control.guarded import (
    ControlLimits,
    ControlSafetyError,
    GuardedActionController,
)
from geometry_dash_ai.control.mock import MockActionBackend
from geometry_dash_ai.control.portal import KdeRemoteDesktopActionBackend

__all__ = [
    "ActionBackend",
    "ControlLimits",
    "ControlPermissionDenied",
    "ControlPermissionLost",
    "ControlSafetyError",
    "ControlUnavailable",
    "GuardedActionController",
    "KdeRemoteDesktopActionBackend",
    "MockActionBackend",
]
