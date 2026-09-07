"""Narrow low-level xdg-desktop-portal transport without XML introspection.

KDE portal XML may contain property names that older dbus-next releases reject
while parsing unrelated interfaces.  This transport uses only fixed portal
methods and fixed Request.Response signals, so it never invokes
``MessageBus.introspect`` or exposes a configurable D-Bus API.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, cast

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
SCREENCAST_INTERFACE = "org.freedesktop.portal.ScreenCast"
REMOTE_DESKTOP_INTERFACE = "org.freedesktop.portal.RemoteDesktop"
DBUS_BUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
DBUS_INTERFACE = "org.freedesktop.DBus"
PEER_INTERFACE = "org.freedesktop.DBus.Peer"


class PortalTransportError(RuntimeError):
    """A fixed portal transport call failed or returned malformed data."""


class PortalTransportTimeout(PortalTransportError):
    """A portal request did not emit a valid response before its deadline."""


@dataclass(frozen=True, slots=True)
class PortalResponse:
    """Validated raw response code and mapping from one known request path."""

    code: int
    results: Mapping[str, object]


class _VariantValue(Protocol):
    value: object


def unwrap_portal_results(response: PortalResponse) -> Mapping[str, object]:
    """Unwrap dbus-next Variant values at the typed portal boundary only."""
    return {key: _unwrap_variant(value) for key, value in response.results.items()}


def validate_object_path(value: object, *, description: str) -> str:
    """Accept a conservative D-Bus object path before using it in a message."""
    if not isinstance(value, str) or not value.startswith("/") or "//" in value:
        raise PortalTransportError(f"{description} is not a valid object path")
    parts = value.split("/")[1:]
    if not parts or any(not _valid_path_part(part) for part in parts):
        raise PortalTransportError(f"{description} is not a valid object path")
    return value


def _valid_path_part(part: str) -> bool:
    return bool(part) and all(
        character.isascii() and (character.isalnum() or character == "_")
        for character in part
    )


class PortalTransport:
    """Typed owner for fixed ScreenCast/RemoteDesktop portal message sequences."""

    def __init__(self, bus: Any, loop: asyncio.AbstractEventLoop, timeout_seconds: float) -> None:
        if not 1.0 <= timeout_seconds <= 120.0:
            raise ValueError("portal transport timeout must be within 1..120 seconds")
        self._bus = bus
        self._loop = loop
        self._timeout_seconds = timeout_seconds

    async def ping(self) -> None:
        await self._method_return(
            PORTAL_BUS,
            PORTAL_PATH,
            PEER_INTERFACE,
            "Ping",
            "",
            [],
        )

    async def screencast_create_session(self, options: Mapping[str, object]) -> PortalResponse:
        return await self._request(SCREENCAST_INTERFACE, "CreateSession", "a{sv}", [dict(options)])

    async def screencast_select_sources(
        self, session_path: str, options: Mapping[str, object]
    ) -> PortalResponse:
        return await self._request(
            SCREENCAST_INTERFACE,
            "SelectSources",
            "oa{sv}",
            [validate_object_path(session_path, description="ScreenCast session"), dict(options)],
        )

    async def screencast_start(
        self, session_path: str, options: Mapping[str, object]
    ) -> PortalResponse:
        return await self._request(
            SCREENCAST_INTERFACE,
            "Start",
            "osa{sv}",
            [
                validate_object_path(session_path, description="ScreenCast session"),
                "",
                dict(options),
            ],
        )

    async def open_pipewire_remote(self, session_path: str) -> int:
        reply = await self._method_return(
            PORTAL_BUS,
            PORTAL_PATH,
            SCREENCAST_INTERFACE,
            "OpenPipeWireRemote",
            "oa{sv}",
            [validate_object_path(session_path, description="ScreenCast session"), {}],
        )
        body = _body(reply)
        if len(body) != 1 or isinstance(body[0], bool) or not isinstance(body[0], int):
            raise PortalTransportError("PipeWire remote FD handle was missing")
        index = body[0]
        unix_fds = getattr(reply, "unix_fds", None)
        if not isinstance(unix_fds, list) or not 0 <= index < len(unix_fds):
            raise PortalTransportError("PipeWire remote FD was missing")
        received = unix_fds[index]
        if isinstance(received, bool) or not isinstance(received, int) or received < 0:
            raise PortalTransportError("PipeWire remote FD was invalid")
        try:
            owned = os.dup(received)
        except OSError as exc:
            raise PortalTransportError("PipeWire remote FD could not be retained") from exc
        with suppress(OSError):
            os.close(received)
        return owned

    async def remote_desktop_create_session(self, options: Mapping[str, object]) -> PortalResponse:
        return await self._request(
            REMOTE_DESKTOP_INTERFACE,
            "CreateSession",
            "a{sv}",
            [dict(options)],
        )

    async def remote_desktop_select_devices(
        self, session_path: str, options: Mapping[str, object]
    ) -> PortalResponse:
        return await self._request(
            REMOTE_DESKTOP_INTERFACE,
            "SelectDevices",
            "oa{sv}",
            [
                validate_object_path(session_path, description="RemoteDesktop session"),
                dict(options),
            ],
        )

    async def remote_desktop_start(
        self, session_path: str, options: Mapping[str, object]
    ) -> PortalResponse:
        return await self._request(
            REMOTE_DESKTOP_INTERFACE,
            "Start",
            "osa{sv}",
            [
                validate_object_path(session_path, description="RemoteDesktop session"),
                "",
                dict(options),
            ],
        )

    async def notify_space_keysym(self, session_path: str, state: int) -> None:
        if state not in {0, 1}:
            raise PortalTransportError("keyboard state is invalid")
        await self._method_return(
            PORTAL_BUS,
            PORTAL_PATH,
            REMOTE_DESKTOP_INTERFACE,
            "NotifyKeyboardKeysym",
            "oa{sv}iu",
            [
                validate_object_path(session_path, description="RemoteDesktop session"),
                {},
                0x20,
                state,
            ],
        )

    async def close_session(self, session_path: str) -> None:
        await self._method_return(
            PORTAL_BUS,
            validate_object_path(session_path, description="portal session"),
            SESSION_INTERFACE,
            "Close",
            "",
            [],
        )

    async def _request(
        self,
        interface: str,
        member: str,
        signature: str,
        body: list[object],
    ) -> PortalResponse:
        reply = await self._method_return(
            PORTAL_BUS,
            PORTAL_PATH,
            interface,
            member,
            signature,
            body,
        )
        reply_body = _body(reply)
        if len(reply_body) != 1:
            raise PortalTransportError("portal did not return a request handle")
        request_path = validate_object_path(reply_body[0], description="portal request handle")
        return await self._wait_response(request_path)

    async def _method_return(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str,
        body: list[object],
    ) -> Any:
        message = _message(destination, path, interface, member, signature, body)
        try:
            reply = await asyncio.wait_for(self._bus.call(message), self._timeout_seconds)
        except TimeoutError as exc:
            raise PortalTransportTimeout(f"portal {member} call timed out") from exc
        except Exception as exc:
            raise PortalTransportError(f"portal {member} call failed") from exc
        if reply is None or not _is_method_return(reply):
            raise PortalTransportError(f"portal {member} returned an error")
        return reply

    async def _wait_response(self, request_path: str) -> PortalResponse:
        future: asyncio.Future[PortalResponse] = self._loop.create_future()
        rule = (
            "type='signal',sender='org.freedesktop.portal.Desktop',"
            f"interface='{REQUEST_INTERFACE}',member='Response',path='{request_path}'"
        )

        def handler(message: Any) -> bool:
            if future.done() or not _is_response_signal(message, request_path):
                return False
            try:
                future.set_result(_parse_response_signal(message))
            except PortalTransportError as exc:
                future.set_exception(exc)
            return False

        self._bus.add_message_handler(handler)
        try:
            await self._add_match(rule)
            try:
                return await asyncio.wait_for(future, self._timeout_seconds)
            except TimeoutError as exc:
                raise PortalTransportTimeout("portal request response timed out") from exc
        finally:
            self._bus.remove_message_handler(handler)
            with suppress(PortalTransportError):
                await self._remove_match(rule)

    async def _add_match(self, rule: str) -> None:
        await self._method_return(DBUS_BUS, DBUS_PATH, DBUS_INTERFACE, "AddMatch", "s", [rule])

    async def _remove_match(self, rule: str) -> None:
        await self._method_return(DBUS_BUS, DBUS_PATH, DBUS_INTERFACE, "RemoveMatch", "s", [rule])


def _message(
    destination: str,
    path: str,
    interface: str,
    member: str,
    signature: str,
    body: list[object],
) -> Any:
    try:
        from dbus_next import Message
    except ImportError as exc:
        raise PortalTransportError("the optional dbus-next dependency is unavailable") from exc
    return Message(
        destination=destination,
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=body,
    )


def _body(message: object) -> list[object]:
    body = getattr(message, "body", None)
    if not isinstance(body, list):
        raise PortalTransportError("portal returned malformed message data")
    return body


def _is_method_return(message: object) -> bool:
    try:
        from dbus_next.constants import MessageType
    except ImportError:
        return False
    return getattr(message, "message_type", None) is MessageType.METHOD_RETURN


def _is_response_signal(message: object, request_path: str) -> bool:
    try:
        from dbus_next.constants import MessageType
    except ImportError:
        return False
    # D-Bus delivers a service's unique sender name, not necessarily its
    # well-known name. The installed AddMatch rule constrains sender to the
    # fixed portal service; validate the remaining signal fields here.
    return (
        getattr(message, "message_type", None) is MessageType.SIGNAL
        and getattr(message, "path", None) == request_path
        and getattr(message, "interface", None) == REQUEST_INTERFACE
        and getattr(message, "member", None) == "Response"
    )


def _parse_response_signal(message: object) -> PortalResponse:
    body = _body(message)
    if len(body) != 2 or isinstance(body[0], bool) or not isinstance(body[0], int):
        raise PortalTransportError("portal response was malformed")
    results = body[1]
    if not isinstance(results, Mapping):
        raise PortalTransportError("portal response results were malformed")
    if any(not isinstance(key, str) for key in results):
        raise PortalTransportError("portal response contained an invalid key")
    return PortalResponse(body[0], dict(results))


def _unwrap_variant(value: object) -> object:
    """Accept only dbus-next Variant wrappers, never arbitrary proxy objects."""
    value_type = type(value)
    if value_type.__module__.startswith("dbus_next") and value_type.__name__ == "Variant":
        return cast(_VariantValue, value).value
    return value


def low_level_portal_ping(timeout_seconds: float = 3.0) -> bool:
    """Safely probe the fixed portal Peer interface without opening a dialog.

    This intentionally performs no object introspection and makes no capture or
    input request. It is used only by the read-only doctor command.
    """
    if not 0.1 <= timeout_seconds <= 10.0:
        raise ValueError("portal probe timeout must be within 0.1..10 seconds")
    try:
        from dbus_next import BusType
        from dbus_next.aio import MessageBus
    except ImportError:
        return False
    loop = asyncio.new_event_loop()
    previous: asyncio.AbstractEventLoop | None
    try:
        try:
            previous = asyncio.get_event_loop()
        except RuntimeError:
            previous = None
        asyncio.set_event_loop(loop)

        async def probe() -> bool:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            try:
                await PortalTransport(bus, loop, timeout_seconds).ping()
                return True
            finally:
                bus.disconnect()

        return loop.run_until_complete(probe())
    except Exception:
        return False
    finally:
        asyncio.set_event_loop(previous)
        loop.close()
