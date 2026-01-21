import time
from typing import Optional

import mss
from PIL import Image, ImageEnhance
import win32gui
from PyQt5 import QtCore, QtGui, QtWidgets

from gl_view import GLFrameView, GL_AVAILABLE
from wgc_capture import WGCCapture, WGC_AVAILABLE

try:
    import dxcam
except ImportError:  # pragma: no cover - optional dependency
    dxcam = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None


DXCAM_AVAILABLE = dxcam is not None
NUMPY_AVAILABLE = np is not None


class StreamWindow(QtWidgets.QMainWindow):
    fps_updated = QtCore.pyqtSignal(float)

    def __init__(self, hwnd: int):
        super().__init__()
        self.hwnd = hwnd
        self.setWindowTitle("Flux de la fenetre")
        self.setMinimumSize(640, 360)

        self.label = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.label.setText("Initialisation du flux...")
        self._gl_view = GLFrameView()
        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self.label)
        self._stack.addWidget(self._gl_view)
        self._stack.setCurrentWidget(self.label)
        self.setCentralWidget(self._stack)

        self._brightness = 1.0
        self._contrast = 1.0
        self._borderless = False
        self._sct = mss.mss()
        self._dxcam = None
        self._capture_backend = "mss"
        self._effects_backend = "numpy" if NUMPY_AVAILABLE else "pillow"
        self._scale_percent = 100
        self._fast_mode = False
        self._use_gpu = False
        self._gpu_available = GL_AVAILABLE
        self._capture_client = False
        self._dxcam_async = False
        self._dxcam_started = False
        self._dxcam_region = None
        self._wgc = WGCCapture(hwnd) if WGC_AVAILABLE else None
        self._wgc_started = False

        self._target_fps = 30
        self._frame_count = 0
        self._fps_last = time.perf_counter()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.set_target_fps(self._target_fps)
        self.timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.timer.stop()
        self._stop_dxcam()
        self._stop_wgc()
        return super().closeEvent(event)

    def set_effects(self, brightness: float, contrast: float) -> None:
        self._brightness = brightness
        self._contrast = contrast
        self._gl_view.set_effects(brightness, contrast)

    def set_target_fps(self, fps: int) -> None:
        if fps <= 0:
            fps = 1
        self._target_fps = fps
        interval = max(1, int(1000 / fps))
        self.timer.setInterval(interval)
        if self._dxcam_async and self._capture_backend == "dxcam":
            self._restart_dxcam()
        if self._capture_backend == "wgc":
            self._restart_wgc()

    def set_scale_percent(self, percent: int) -> None:
        self._scale_percent = max(10, min(100, int(percent)))

    def set_fast_mode(self, enabled: bool) -> None:
        self._fast_mode = bool(enabled)
        self._gl_view.set_fast_mode(enabled)

    def set_gpu_mode(self, enabled: bool) -> None:
        if enabled and not self._gpu_available:
            return
        self._use_gpu = bool(enabled)
        if self._use_gpu:
            self._stack.setCurrentWidget(self._gl_view)
        else:
            self._stack.setCurrentWidget(self.label)

    def set_capture_client_area(self, enabled: bool) -> None:
        self._capture_client = bool(enabled)

    def set_dxcam_async(self, enabled: bool) -> None:
        self._dxcam_async = bool(enabled)
        if self._capture_backend == "dxcam":
            if self._dxcam_async:
                self._restart_dxcam()
            else:
                self._stop_dxcam()

    def set_capture_backend(self, backend: str) -> None:
        backend = backend.lower()
        if backend == self._capture_backend:
            return
        if backend == "dxcam" and not DXCAM_AVAILABLE:
            return
        if backend == "wgc" and not WGC_AVAILABLE:
            return
        if self._capture_backend == "dxcam":
            self._stop_dxcam()
        if self._capture_backend == "wgc":
            self._stop_wgc()
        self._capture_backend = backend
        self._init_capture_backend()
        if self._capture_backend == "dxcam" and self._dxcam_async:
            self._restart_dxcam()
        if self._capture_backend == "wgc":
            self._start_wgc()

    def set_effects_backend(self, backend: str) -> None:
        backend = backend.lower()
        if backend == "numpy" and not NUMPY_AVAILABLE:
            return
        if backend not in ("numpy", "pillow"):
            return
        self._effects_backend = backend

    def toggle_fullscreen(self) -> None:
        self._borderless = not self._borderless
        if self._borderless:
            self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
            self.showFullScreen()
        else:
            self.setWindowFlag(QtCore.Qt.FramelessWindowHint, False)
            self.showNormal()
        self.show()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.toggle_fullscreen()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        self.toggle_fullscreen()

    def update_frame(self) -> None:
        if not win32gui.IsWindow(self.hwnd):
            self.label.setText("Fenetre cible introuvable ou fermee.")
            return
        try:
            left, top, right, bottom = self._get_capture_rect()
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                self.label.setText("Fenetre cible minimisee ou hors ecran.")
                return

            frame, f_width, f_height = self._grab_frame(left, top, right, bottom, width, height)
            if frame is None:
                return

            if self._use_gpu:
                data, out_w, out_h = self._frame_to_gpu_bytes(frame, f_width, f_height)
                if data is None:
                    return
                self._present_gpu_frame(data, out_w, out_h)
            else:
                pixmap = self._frame_to_pixmap(frame, f_width, f_height)
                if pixmap is None:
                    return
                self._present_pixmap(pixmap)
            self._tick_fps()
        except Exception as exc:  # pragma: no cover - UI feedback only
            self.label.setText(f"Erreur de capture: {exc}")

    def _init_capture_backend(self) -> None:
        if self._capture_backend == "dxcam" and DXCAM_AVAILABLE:
            if self._dxcam is None:
                self._dxcam = dxcam.create(output_color="BGRA")
        else:
            self._dxcam = None

    def _grab_frame(self, left: int, top: int, right: int, bottom: int, width: int, height: int):
        if self._capture_backend == "wgc" and WGC_AVAILABLE:
            self._ensure_wgc_started()
            frame = self._wgc.get_latest() if self._wgc else None
            return self._coerce_wgc_frame(frame, left, top, right, bottom)
        if self._capture_backend == "dxcam" and DXCAM_AVAILABLE:
            if self._dxcam is None:
                self._init_capture_backend()
            region = (left, top, right, bottom)
            if self._dxcam_async:
                self._ensure_dxcam_started(region)
                frame = self._dxcam.get_latest_frame() if self._dxcam else None
            else:
                frame = self._dxcam.grab(region=region)
            if frame is None:
                return None, 0, 0
            return frame, frame.shape[1], frame.shape[0]

        monitor = {"left": left, "top": top, "width": width, "height": height}
        raw = self._sct.grab(monitor)
        return raw, raw.width, raw.height

    def _stop_dxcam(self) -> None:
        if self._dxcam and self._dxcam_started:
            try:
                self._dxcam.stop()
            except Exception:
                pass
        self._dxcam_started = False
        self._dxcam_region = None

    def _restart_dxcam(self) -> None:
        self._stop_dxcam()
        # Start lazily on next grab with current region.

    def _ensure_dxcam_started(self, region) -> None:
        if not self._dxcam:
            return
        if self._dxcam_started and self._dxcam_region == region:
            return
        self._stop_dxcam()
        try:
            self._dxcam.start(target_fps=self._target_fps, region=region)
        except TypeError:
            try:
                self._dxcam.start(target_fps=self._target_fps)
            except TypeError:
                self._dxcam.start()
        self._dxcam_started = True
        self._dxcam_region = region

    def _start_wgc(self) -> None:
        if not self._wgc or self._wgc_started:
            return
        self._wgc_started = self._wgc.start(self._target_fps)
        if not self._wgc_started:
            self._capture_backend = "mss"
            self._init_capture_backend()
            self.label.setText("WGC indisponible, retour MSS.")

    def _restart_wgc(self) -> None:
        self._stop_wgc()
        self._start_wgc()

    def _ensure_wgc_started(self) -> None:
        if not self._wgc_started:
            self._start_wgc()

    def _stop_wgc(self) -> None:
        if self._wgc:
            self._wgc.stop()
        self._wgc_started = False

    def _coerce_wgc_frame(self, frame, left: int, top: int, right: int, bottom: int):
        if frame is None:
            return None, 0, 0
        data = frame
        for attr in ("image", "frame", "data", "buffer"):
            if hasattr(data, attr):
                data = getattr(data, attr)
                break

        if isinstance(data, tuple) and len(data) >= 3:
            buf, w, h = data[0], int(data[1]), int(data[2])
            return buf, w, h

        if np is not None and isinstance(data, np.ndarray):
            data = self._crop_from_wgc(data, left, top, right, bottom)
            return data, data.shape[1], data.shape[0]

        w = getattr(data, "width", None)
        h = getattr(data, "height", None)
        if w and h and isinstance(data, (bytes, bytearray, memoryview)):
            return data, int(w), int(h)

        return None, 0, 0

    def _crop_from_wgc(self, frame, left: int, top: int, right: int, bottom: int):
        if np is None:
            return frame
        target_left, target_top, target_right, target_bottom = left, top, right, bottom
        mon_rect = self._wgc.get_monitor_rect() if self._wgc else None
        if not mon_rect:
            return frame
        mon_left, mon_top, mon_right, mon_bottom = mon_rect
        rel_left = max(0, target_left - mon_left)
        rel_top = max(0, target_top - mon_top)
        rel_right = min(mon_right - mon_left, target_right - mon_left)
        rel_bottom = min(mon_bottom - mon_top, target_bottom - mon_top)
        if rel_right <= rel_left or rel_bottom <= rel_top:
            return frame
        return frame[rel_top:rel_bottom, rel_left:rel_right]

    def _get_capture_rect(self):
        if not self._capture_client:
            return win32gui.GetWindowRect(self.hwnd)
        left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
        tl = win32gui.ClientToScreen(self.hwnd, (left, top))
        br = win32gui.ClientToScreen(self.hwnd, (right, bottom))
        return tl[0], tl[1], br[0], br[1]

    def _maybe_crop_client(self, frame, left: int, top: int, right: int, bottom: int):
        if not self._capture_client or np is None:
            return frame
        win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(self.hwnd)
        win_w = win_right - win_left
        win_h = win_bottom - win_top
        if frame.shape[1] != win_w or frame.shape[0] != win_h:
            return frame
        cl_left, cl_top, cl_right, cl_bottom = win32gui.GetClientRect(self.hwnd)
        tl = win32gui.ClientToScreen(self.hwnd, (cl_left, cl_top))
        br = win32gui.ClientToScreen(self.hwnd, (cl_right, cl_bottom))
        off_x = tl[0] - win_left
        off_y = tl[1] - win_top
        c_w = br[0] - tl[0]
        c_h = br[1] - tl[1]
        if off_x < 0 or off_y < 0 or c_w <= 0 or c_h <= 0:
            return frame
        return frame[off_y : off_y + c_h, off_x : off_x + c_w]

    def _frame_to_pixmap(self, frame, width: int, height: int) -> Optional[QtGui.QPixmap]:
        scale = max(0.1, self._scale_percent / 100.0)
        out_w = max(1, int(width * scale))
        out_h = max(1, int(height * scale))
        use_fast = self._fast_mode

        if self._effects_backend == "numpy" and NUMPY_AVAILABLE:
            pixmap = self._pixmap_from_numpy(frame, width, height, out_w, out_h, use_fast)
            if pixmap is not None:
                return pixmap

        return self._pixmap_from_pillow(frame, width, height, out_w, out_h, use_fast)

    def _pixmap_from_numpy(
        self,
        frame,
        width: int,
        height: int,
        out_w: int,
        out_h: int,
        use_fast: bool,
    ) -> Optional[QtGui.QPixmap]:
        if np is None:
            return None

        if isinstance(frame, mss.base.ScreenShot):
            arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape(height, width, 4)
        else:
            arr = np.asarray(frame)
            if arr.ndim != 3:
                return None

        if out_w != width or out_h != height:
            y_idx = (np.linspace(0, height - 1, out_h)).astype(np.int32)
            x_idx = (np.linspace(0, width - 1, out_w)).astype(np.int32)
            arr = arr[y_idx[:, None], x_idx]
            height, width = arr.shape[0], arr.shape[1]

        if arr.shape[2] == 4:
            rgb = arr[:, :, :3].astype(np.float32)
            alpha = arr[:, :, 3:4]
        else:
            rgb = arr.astype(np.float32)
            alpha = None

        if self._contrast != 1.0:
            rgb = (rgb - 128.0) * self._contrast + 128.0
        if self._brightness != 1.0:
            rgb = rgb * self._brightness
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

        if alpha is not None:
            out = np.concatenate((rgb, alpha), axis=2)
            qimage = QtGui.QImage(
                out.data,
                width,
                height,
                QtGui.QImage.Format_ARGB32,
            ).copy()
        else:
            out = rgb
            qimage = QtGui.QImage(
                out.data,
                width,
                height,
                QtGui.QImage.Format_BGR888,
            ).copy()

        return QtGui.QPixmap.fromImage(qimage)

    def _pixmap_from_pillow(
        self,
        frame,
        width: int,
        height: int,
        out_w: int,
        out_h: int,
        use_fast: bool,
    ) -> Optional[QtGui.QPixmap]:
        if isinstance(frame, mss.base.ScreenShot):
            img = Image.frombytes("RGB", (width, height), frame.rgb)
        else:
            if np is None:
                return None
            arr = np.asarray(frame)
            if arr.ndim != 3 or arr.shape[2] < 3:
                return None
            # dxcam returns BGR(A); convert to RGB for Pillow.
            rgb = arr[:, :, :3][:, :, ::-1]
            img = Image.fromarray(rgb, mode="RGB")

        if out_w != width or out_h != height:
            resample = Image.NEAREST if use_fast else Image.BILINEAR
            img = img.resize((out_w, out_h), resample=resample)

        if self._brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(self._brightness)
        if self._contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(self._contrast)

        qimage = QtGui.QImage(
            img.tobytes(),
            img.width,
            img.height,
            QtGui.QImage.Format_RGB888,
        ).copy()
        return QtGui.QPixmap.fromImage(qimage)

    def _frame_to_gpu_bytes(self, frame, width: int, height: int):
        scale = max(0.1, self._scale_percent / 100.0)
        out_w = max(1, int(width * scale))
        out_h = max(1, int(height * scale))

        if out_w != width or out_h != height:
            if NUMPY_AVAILABLE:
                if isinstance(frame, mss.base.ScreenShot):
                    arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape(height, width, 4)
                else:
                    arr = np.asarray(frame)
                y_idx = (np.linspace(0, height - 1, out_h)).astype(np.int32)
                x_idx = (np.linspace(0, width - 1, out_w)).astype(np.int32)
                arr = arr[y_idx[:, None], x_idx]
                return arr.tobytes(), out_w, out_h
            # No numpy: fallback to full size to avoid blank output.

        if isinstance(frame, mss.base.ScreenShot):
            return frame.bgra, width, height
        if isinstance(frame, (bytes, bytearray, memoryview)):
            return frame, width, height
        if np is None:
            return None, 0, 0
        return np.asarray(frame).tobytes(), width, height

    def _present_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        label_size = self.label.size()
        if pixmap.size() == label_size:
            self.label.setPixmap(pixmap)
            return

        transform = QtCore.Qt.FastTransformation if self._fast_mode else QtCore.Qt.SmoothTransformation
        scaled = pixmap.scaled(label_size, QtCore.Qt.KeepAspectRatio, transform)
        self.label.setPixmap(scaled)

    def _present_gpu_frame(self, data: bytes, width: int, height: int) -> None:
        self._gl_view.set_frame(data, width, height)

    def _tick_fps(self) -> None:
        self._frame_count += 1
        now = time.perf_counter()
        elapsed = now - self._fps_last
        if elapsed >= 1.0:
            fps = self._frame_count / elapsed
            self.fps_updated.emit(fps)
            self._frame_count = 0
            self._fps_last = now
