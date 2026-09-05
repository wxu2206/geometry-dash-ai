"""Optional local Tk debug viewer for observe-only snapshots."""

from __future__ import annotations

import base64
from math import isfinite
from typing import Any

import numpy as np

MAX_PREVIEW_PIXELS = 3_840 * 2_160


class DebugViewerUnavailable(RuntimeError):
    """Raised when a local GUI preview cannot be opened in the desktop session."""


class TkDebugViewer:
    """A bounded single-window renderer; no global keyboard or mouse hooks are used."""

    def __init__(
        self, title: str = "Geometry Dash AI — observe only", preview_scale: float = 1.0
    ) -> None:
        if (
            isinstance(preview_scale, bool)
            or not isinstance(preview_scale, (int, float))
            or not isfinite(preview_scale)
            or not 0.1 <= preview_scale <= 4.0
        ):
            raise ValueError("preview scale must be finite and within [0.1, 4]")
        try:
            import tkinter as tk

            self._tk = tk
            self._root = tk.Tk()
            self._root.title(title)
            self._label = tk.Label(self._root)
            self._label.pack()
        except Exception as exc:
            raise DebugViewerUnavailable("could not open local Tk preview window") from exc
        self._closed = False
        self._photo: Any | None = None
        self._preview_scale = float(preview_scale)

    def show(self, image: Any, status: str) -> None:
        if self._closed:
            return
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("viewer requires RGB image data")
        displayed = scale_preview(image, self._preview_scale)
        height, width, _ = displayed.shape
        ppm = f"P6 {width} {height} 255\n".encode("ascii") + displayed.tobytes()
        photo = self._tk.PhotoImage(data=base64.b64encode(ppm))
        self._label.configure(image=photo, text=status, compound="bottom")
        self._photo = photo
        self._root.update_idletasks()
        self._root.update()

    def close(self) -> None:
        if not self._closed:
            self._root.destroy()
            self._closed = True


def scale_preview(image: Any, scale: float) -> Any:
    """Nearest-neighbor preview scaling with a strict output-allocation ceiling."""
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
    ):
        raise ValueError("viewer requires RGB uint8 image data")
    if (
        isinstance(scale, bool)
        or not isinstance(scale, (int, float))
        or not isfinite(scale)
        or not 0.1 <= scale <= 4.0
    ):
        raise ValueError("preview scale must be finite and within [0.1, 4]")
    height, width, _ = image.shape
    target_width = max(1, round(width * float(scale)))
    target_height = max(1, round(height * float(scale)))
    if target_width * target_height > MAX_PREVIEW_PIXELS:
        raise ValueError("preview dimensions exceed the bounded viewer budget")
    if target_width == width and target_height == height:
        return image
    y_indices = np.minimum((np.arange(target_height) / float(scale)).astype(int), height - 1)
    x_indices = np.minimum((np.arange(target_width) / float(scale)).astype(int), width - 1)
    return np.ascontiguousarray(image[y_indices[:, None], x_indices[None, :]])
