"""Keyboard-only xdg-desktop-portal RemoteDesktop action backend.

This is intentionally not a general keyboard automation API.  The only event
it can emit is the Geometry Dash action key (Space), through a session that KDE
must approve during the current application launch.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from geometry_dash_ai.capture.portal import parse_portal_response
from geometry_dash_ai.control.backend import (
    ControlPermissionDenied,
    ControlPermissionLost,
    ControlUnavailable,
)

_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"
_REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
_KEYBOARD_DEVICE = 1
_SPACE_KEYSYM = 0x20
_KEY_RELEASED = 0
_KEY_PRESSED = 1


class KdeRemoteDesktopActionBackend:
    """One-session, keyboard-only, Space-only portal backend."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        if not 1.0 <= timeout_seconds <= 120.0:
            raise ValueError("control portal timeout must be within 1..120 seconds")
        self._timeout_seconds = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._bus: Any | None = None
        self._remote: Any | None = None
        self._session_path: str | None = None
        self._granted = False
        self._healthy = False
        self._held = False
        self._closed = False
        try:
            self._loop.run_until_complete(self._request_permission())
        except Exception:
            self.close()
            raise

    @property
    def permission_granted(self) -> bool:
        return self._granted

    @property
    def healthy(self) -> bool:
        return self._healthy and not self._closed

    async def _request_permission(self) -> None:
        try:
            from dbus_next import BusType, Variant
            from dbus_next.aio import MessageBus
        except ImportError as exc:
            raise ControlUnavailable(
                "live control requires the optional pure-Python dbus-next dependency"
            ) from exc
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            root = await self._bus.introspect(_PORTAL_BUS, _PORTAL_PATH)
            portal = self._bus.get_proxy_object(_PORTAL_BUS, _PORTAL_PATH, root)
            self._remote = portal.get_interface(_REMOTE_DESKTOP_IFACE)
            created = await self._await_request(
                await self._remote.call_create_session(
                    {
                        "handle_token": Variant("s", "geometry_dash_control"),
                        "session_handle_token": Variant("s", "geometry_dash_control_session"),
                    }
                )
            )
            session = created.get("session_handle")
            if not isinstance(session, str) or not session.startswith("/"):
                raise ControlUnavailable("RemoteDesktop portal returned an invalid session")
            self._session_path = session
            await self._await_request(
                await self._remote.call_select_devices(
                    session,
                    {
                        "handle_token": Variant("s", "geometry_dash_keyboard"),
                        "types": Variant("u", _KEYBOARD_DEVICE),
                    },
                )
            )
            started = await self._await_request(
                await self._remote.call_start(
                    session,
                    "",
                    {"handle_token": Variant("s", "geometry_dash_control_start")},
                )
            )
            devices = started.get("devices")
            if isinstance(devices, bool) or not isinstance(devices, int):
                raise ControlUnavailable("RemoteDesktop portal returned invalid device metadata")
            if not devices & _KEYBOARD_DEVICE:
                raise ControlPermissionDenied(
                    "KDE did not grant keyboard control; Observe and Shadow remain available"
                )
            self._granted = True
            self._healthy = True
        except ControlUnavailable:
            raise
        except Exception as exc:
            raise ControlUnavailable(
                "could not obtain KDE keyboard permission; Observe and Shadow remain available"
            ) from exc

    async def _await_request(self, request_path: object) -> dict[str, object]:
        if not isinstance(request_path, str) or not request_path.startswith("/"):
            raise ControlUnavailable("RemoteDesktop portal returned an invalid request handle")
        if self._bus is None:
            raise ControlUnavailable("RemoteDesktop user bus is unavailable")
        introspection = await self._bus.introspect(_PORTAL_BUS, request_path)
        request = self._bus.get_proxy_object(_PORTAL_BUS, request_path, introspection)
        interface = request.get_interface(_REQUEST_IFACE)
        future: asyncio.Future[dict[str, object]] = self._loop.create_future()

        def response(code: object, results: object) -> None:
            if future.done():
                return
            try:
                parsed = parse_portal_response(code, results)
                future.set_result(dict(parsed))
            except Exception as exc:
                denied = (
                    isinstance(code, int)
                    and not isinstance(code, bool)
                    and code in (1, 2)
                )
                future.set_exception(
                    ControlPermissionDenied(
                        "keyboard-control permission was denied or cancelled; no input was enabled"
                    )
                    if denied
                    else ControlUnavailable(str(exc))
                )

        interface.on_response(response)
        try:
            return await asyncio.wait_for(future, self._timeout_seconds)
        except TimeoutError as exc:
            raise ControlUnavailable("keyboard-control permission request timed out") from exc
        finally:
            interface.off_response(response)

    def press_action(self) -> None:
        self._notify(_KEY_PRESSED)
        self._held = True

    def release_action(self) -> None:
        if not self._held:
            return
        if self._closed or self._remote is None or self._session_path is None:
            self._held = False
            return
        try:
            self._notify(_KEY_RELEASED)
        finally:
            self._held = False

    def _notify(self, state: int) -> None:
        if not self.healthy or self._remote is None or self._session_path is None:
            raise ControlPermissionLost("KDE keyboard-control permission is unavailable")
        try:
            self._loop.run_until_complete(
                self._remote.call_notify_keyboard_keysym(
                    self._session_path, {}, _SPACE_KEYSYM, state
                )
            )
        except Exception as exc:
            self._healthy = False
            raise ControlPermissionLost(
                "KDE keyboard-control permission ended; the action key was released"
            ) from exc

    def close(self) -> None:
        if self._closed:
            return
        if self._held:
            with suppress(Exception):
                self.release_action()
        self._healthy = False
        self._granted = False
        if self._bus is not None and self._session_path is not None:
            with suppress(Exception):
                self._loop.run_until_complete(self._close_session())
        if self._bus is not None:
            with suppress(Exception):
                self._bus.disconnect()
        with suppress(Exception):
            self._loop.close()
        self._closed = True

    async def _close_session(self) -> None:
        assert self._bus is not None and self._session_path is not None
        introspection = await self._bus.introspect(_PORTAL_BUS, self._session_path)
        session = self._bus.get_proxy_object(_PORTAL_BUS, self._session_path, introspection)
        await session.get_interface(_SESSION_IFACE).call_close()
