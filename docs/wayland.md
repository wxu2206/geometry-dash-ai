# KDE Wayland permission model

The application never bypasses KDE capture or input policy. Screen capture calls
only the user-session `org.freedesktop.portal.ScreenCast` flow: CreateSession,
SelectSources for exactly one window or monitor, Start, and OpenPipeWireRemote.
KDE owns the consent dialog. The returned PipeWire FD is ephemeral. Because the
portal's optional `size` property is compositor-coordinate metadata, a fixed,
bounded local GStreamer caps probe first discovers the actual video dimensions.
The reader validates the configured crop against those dimensions before starting
its fixed `shell=False` pipeline. A leaky one-frame queue drops stale frames, and
`videocrop` removes non-game monitor pixels before the Python pipe whenever a
crop is configured.

The portal transport does not use full object XML introspection. It uses fixed,
typed low-level D-Bus messages and waits for the exact request-path
`org.freedesktop.portal.Request.Response` signal. This works around portal XML
members that some `dbus-next` versions reject before ScreenCast is reached.

Live input is separately requested through `org.freedesktop.portal.RemoteDesktop`:
CreateSession, SelectDevices with the keyboard bit only, Start, then
NotifyKeyboardKeysym for Space press/release. It is unavailable before permission,
arming, and explicit Start. Sessions close on denial, error, emergency, and exit.

No service name, object path, interface, method, command, or key symbol comes from
configuration. No restore token is persisted. If the user bus, portal interface,
GStreamer PipeWire plugin, or KDE implementation is unavailable, the app reports
that capability as blocked while synthetic/Observe features remain usable. Do
not install host packages or weaken compositor policy on Bazzite.
