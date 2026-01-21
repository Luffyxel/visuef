import threading
from typing import Optional

import win32api
import win32gui

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None

try:
    import windows_capture as wcap
except Exception:  # pragma: no cover - optional dependency
    wcap = None


WGC_AVAILABLE = wcap is not None


class WGCCapture:
    def __init__(self, hwnd: int):
        self._hwnd = hwnd
        self._capture = None
        self._control = None
        self._latest = None
        self._lock = threading.Lock()
        self._fps = 30
        self._running = False
        self._monitor_rect = None

    def start(self, fps: int) -> bool:
        if not WGC_AVAILABLE:
            return False
        if fps <= 0:
            fps = 1
        self._fps = fps
        self.stop()

        title = win32gui.GetWindowText(self._hwnd)
        monitor_index, monitor_rect = self._get_monitor_index()
        self._monitor_rect = monitor_rect
        interval = max(1, int(1000 / fps))
        try:
            self._capture = wcap.WindowsCapture(
                monitor_index=monitor_index,
                minimum_update_interval=interval,
                cursor_capture=False,
                draw_border=False,
                dirty_region=True,
            )
        except Exception:
            self._capture = None
            return False

        @self._capture.event
        def on_frame_arrived(frame, control):
            buf = getattr(frame, "frame_buffer", None)
            if buf is None:
                return
            if np is not None:
                buf = np.ascontiguousarray(buf)
            else:
                try:
                    buf = buf.copy()
                except Exception:
                    return
            with self._lock:
                self._latest = buf

        @self._capture.event
        def on_closed():
            self._running = False

        try:
            self._control = self._capture.start_free_threaded()
        except Exception:
            try:
                self._capture.start()
            except Exception:
                self._capture = None
                return False

        self._running = True
        return True

    def stop(self) -> None:
        self._running = False
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:
                pass
        self._control = None
        self._capture = None

    def get_latest(self):
        with self._lock:
            return self._latest

    def get_monitor_rect(self):
        return self._monitor_rect

    def _get_monitor_index(self):
        rect = win32gui.GetWindowRect(self._hwnd)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        monitors = win32api.EnumDisplayMonitors()
        for idx, (_, _, mrect) in enumerate(monitors):
            if mrect[0] <= cx < mrect[2] and mrect[1] <= cy < mrect[3]:
                return idx, mrect
        if monitors:
            return 0, monitors[0][2]
        return 0, None
