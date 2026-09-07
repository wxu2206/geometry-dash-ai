from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import suppress
from typing import Any
from unittest.mock import patch

from dbus_next import Message, Variant
from dbus_next.constants import MessageType

from geometry_dash_ai.capture.portal import KdeScreenCastPortal
from geometry_dash_ai.control.portal import KdeRemoteDesktopActionBackend
from geometry_dash_ai.portal_transport import (
    PORTAL_BUS,
    REQUEST_INTERFACE,
    PortalTransport,
    PortalTransportError,
    validate_object_path,
)


def _return(body: list[object], unix_fds: list[int] | None = None) -> Message:
    return Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=1,
        body=body,
        unix_fds=unix_fds or [],
    )


class _FakeBus:
    def __init__(self) -> None:
        self.calls: list[Message] = []
        self.handlers: list[Any] = []
        self._request_number = 0
        self._pending_path: str | None = None
        self._pending_results: dict[str, object] = {}
        self._pending_code = 0
        self._fd_read, self._fd_write = os.pipe()

    async def call(self, message: Message) -> Message:
        self.calls.append(message)
        if message.member in {"AddMatch", "RemoveMatch", "Ping", "Close", "NotifyKeyboardKeysym"}:
            if message.member == "AddMatch":
                asyncio.get_running_loop().call_soon(self._emit_response)
            return _return([])
        if message.member == "OpenPipeWireRemote":
            return _return([0], [self._fd_read])
        if message.member in {"CreateSession", "SelectSources", "SelectDevices", "Start"}:
            self._request_number += 1
            self._pending_path = (
                "/org/freedesktop/portal/desktop/request/"
                f"test_{self._request_number}"
            )
            if message.member == "CreateSession":
                self._pending_results = {
                    "session_handle": Variant("o", "/org/freedesktop/portal/desktop/session/test")
                }
            elif message.member == "Start":
                self._pending_results = {
                    "streams": Variant(
                        "a(ua{sv})",
                        [[7, {"size": Variant("(ii)", [320, 180])}]],
                    ),
                    "devices": Variant("u", 1),
                }
            else:
                self._pending_results = {}
            return _return([self._pending_path])
        raise AssertionError(f"unexpected portal member {message.member}")

    def add_message_handler(self, handler: Any) -> None:
        self.handlers.append(handler)

    def remove_message_handler(self, handler: Any) -> None:
        self.handlers.remove(handler)

    def introspect(self, *args: object) -> None:
        del args
        raise AssertionError("full XML introspection must not be called")

    def _emit_response(self) -> None:
        assert self._pending_path is not None
        message = Message(
            message_type=MessageType.SIGNAL,
            sender=PORTAL_BUS,
            path=self._pending_path,
            interface=REQUEST_INTERFACE,
            member="Response",
            signature="ua{sv}",
            body=[self._pending_code, self._pending_results],
        )
        for handler in tuple(self.handlers):
            handler(message)

    def close_fds(self) -> None:
        for descriptor in (self._fd_read, self._fd_write):
            with suppress(OSError):
                os.close(descriptor)

    async def connect(self) -> _FakeBus:
        return self

    def disconnect(self) -> None:
        pass


class _FakeMessageBus(_FakeBus):
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        super().__init__()


class PortalTransportTests(unittest.TestCase):
    def test_high_level_backends_never_call_introspect(self) -> None:
        class BusType:
            SESSION = object()

        async def screencast() -> tuple[KdeScreenCastPortal, int]:
            portal = KdeScreenCastPortal()
            portal._loop = asyncio.get_running_loop()
            grant = await portal._request_async(_FakeMessageBus, BusType, Variant)
            return portal, grant.remote_fd

        portal, remote_fd = asyncio.run(screencast())
        try:
            self.assertIsInstance(portal._bus, _FakeMessageBus)
            assert isinstance(portal._bus, _FakeMessageBus)
            self.assertFalse(any(message.member == "Introspect" for message in portal._bus.calls))
        finally:
            os.close(remote_fd)
            assert isinstance(portal._bus, _FakeMessageBus)
            portal._bus.close_fds()
            portal._bus = None
            portal._transport = None
            portal._session_path = None
            portal._loop = None

        with patch("dbus_next.aio.MessageBus", _FakeMessageBus):
            backend = KdeRemoteDesktopActionBackend()
        try:
            assert isinstance(backend._bus, _FakeMessageBus)
            self.assertFalse(any(message.member == "Introspect" for message in backend._bus.calls))
            backend.press_action()
            backend.release_action()
        finally:
            backend.close()
            assert isinstance(backend._bus, _FakeMessageBus)
            backend._bus.close_fds()

    def test_screencast_messages_responses_and_fd_use_no_introspection(self) -> None:
        async def exercise() -> tuple[_FakeBus, int]:
            bus = _FakeBus()
            transport = PortalTransport(bus, asyncio.get_running_loop(), 1.0)
            created = await transport.screencast_create_session({"token": Variant("s", "x")})
            session = created.results["session_handle"]
            assert isinstance(session, Variant)
            selected = await transport.screencast_select_sources(session.value, {})
            self.assertEqual(selected.code, 0)
            started = await transport.screencast_start(session.value, {})
            self.assertEqual(started.code, 0)
            remote_fd = await transport.open_pipewire_remote(session.value)
            return bus, remote_fd

        bus, remote_fd = asyncio.run(exercise())
        try:
            relevant = [message for message in bus.calls if message.destination == PORTAL_BUS]
            self.assertEqual(
                [(message.interface, message.member, message.signature) for message in relevant],
                [
                    ("org.freedesktop.portal.ScreenCast", "CreateSession", "a{sv}"),
                    ("org.freedesktop.portal.ScreenCast", "SelectSources", "oa{sv}"),
                    ("org.freedesktop.portal.ScreenCast", "Start", "osa{sv}"),
                    ("org.freedesktop.portal.ScreenCast", "OpenPipeWireRemote", "oa{sv}"),
                ],
            )
            self.assertEqual(relevant[1].body[0], "/org/freedesktop/portal/desktop/session/test")
            self.assertEqual(relevant[2].body[1], "")
            self.assertEqual(bus.handlers, [])
            os.fstat(remote_fd)
        finally:
            os.close(remote_fd)
            bus.close_fds()

    def test_remote_messages_are_keyboard_only_and_never_introspect(self) -> None:
        async def exercise() -> _FakeBus:
            bus = _FakeBus()
            transport = PortalTransport(bus, asyncio.get_running_loop(), 1.0)
            created = await transport.remote_desktop_create_session({})
            session = created.results["session_handle"]
            assert isinstance(session, Variant)
            await transport.remote_desktop_select_devices(session.value, {"types": Variant("u", 1)})
            await transport.remote_desktop_start(session.value, {})
            await transport.notify_space_keysym(session.value, 1)
            await transport.notify_space_keysym(session.value, 0)
            await transport.close_session(session.value)
            return bus

        bus = asyncio.run(exercise())
        try:
            methods = [
                (message.interface, message.member, message.signature)
                for message in bus.calls
            ]
            self.assertIn(
                ("org.freedesktop.portal.RemoteDesktop", "SelectDevices", "oa{sv}"),
                methods,
            )
            self.assertIn(
                ("org.freedesktop.portal.RemoteDesktop", "NotifyKeyboardKeysym", "oa{sv}iu"),
                methods,
            )
            notify = [message for message in bus.calls if message.member == "NotifyKeyboardKeysym"]
            self.assertEqual([message.body[2:4] for message in notify], [[0x20, 1], [0x20, 0]])
            self.assertFalse(any(message.member == "Introspect" for message in bus.calls))
        finally:
            bus.close_fds()

    def test_response_failure_malformed_data_and_path_validation_are_rejected(self) -> None:
        self.assertEqual(
            validate_object_path("/org/freedesktop/portal/desktop/request/a_1", description="test"),
            "/org/freedesktop/portal/desktop/request/a_1",
        )
        for value in ("not/a/path", "/bad-name", "/double//slash", 3):
            with self.assertRaises(PortalTransportError):
                validate_object_path(value, description="test")

        async def malformed() -> None:
            bus = _FakeBus()
            bus._pending_code = 99
            transport = PortalTransport(bus, asyncio.get_running_loop(), 1.0)
            response = await transport.screencast_create_session({})
            self.assertEqual(response.code, 99)
            bus.close_fds()

        asyncio.run(malformed())


if __name__ == "__main__":
    unittest.main()
