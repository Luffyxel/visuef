import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import mss
from PIL import Image, ImageEnhance
import win32api
import win32gui
from PyQt5 import QtCore, QtGui, QtWidgets

from gl_view import GLFrameView, GL_AVAILABLE
from wgc_capture import WGCCapture, WGC_AVAILABLE
from logger_utils import get_logger

try:
    import dxcam
except ImportError:  # pragma: no cover - optional dependency
    dxcam = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None


DXCAM_AVAILABLE = dxcam is not None
NUMPY_AVAILABLE = np is not None
OPENCV_AVAILABLE = cv2 is not None


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
        self._overlay = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self._overlay.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._overlay.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self._overlay.setStyleSheet("background: transparent;")
        self._overlay.setText("")
        self._gpu_container = QtWidgets.QWidget()
        gpu_layout = QtWidgets.QGridLayout()
        gpu_layout.setContentsMargins(0, 0, 0, 0)
        gpu_layout.addWidget(self._gl_view, 0, 0)
        gpu_layout.addWidget(self._overlay, 0, 0)
        self._gpu_container.setLayout(gpu_layout)
        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self.label)
        self._stack.addWidget(self._gpu_container)
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
        self._dxcam_output_idx = None
        self._dxcam_output_rect = None
        self._dxcam_last_error = 0.0
        self._wgc = WGCCapture(hwnd) if WGC_AVAILABLE else None
        self._wgc_started = False
        self._auto_foreground_fallback = True
        self._fallback_last_log = 0.0
        self._crop_left = 0
        self._crop_top = 0
        self._crop_right = 0
        self._crop_bottom = 0
        self._blob_params = {
            "enabled": False,
            "threshold": 25,
            "min_area": 600,
            "max_area": 0,
            "min_w": 10,
            "min_h": 10,
            "max_w": 0,
            "max_h": 0,
            "blur": 5,
            "dilate": 2,
            "erode": 0,
            "scale": 50,
            "max_blobs": 10,
            "skip": 0,
            "max_fps": 15,
            "alpha": 0.0,
            "show_boxes": True,
            "show_centers": False,
            "show_mask": False,
            "show_labels": False,
            "label_size": 10,
            "label_offset": (6, -6),
            "label_color": (220, 230, 255),
            "link_enabled": False,
            "link_max": 1,
            "link_dist": 250,
            "link_width": 1,
            "link_color": (120, 220, 120),
            "line": 2,
            "color": (0, 255, 0),
        }
        self._blob_prev = None
        self._blob_bg = None
        self._blob_skip_count = 0
        self._blob_last_boxes = []
        self._blob_last_mask = None
        self._blob_last_submit = 0.0
        self._blob_result_id = 0
        self._blob_overlay_pixmap = None
        self._blob_overlay_params = None
        self._blob_executor = ThreadPoolExecutor(max_workers=1)
        self._blob_future = None
        self._blob_pending = None
        self._blob_lock = threading.Lock()
        self._blob_reset = False

        self._target_fps = 30
        self._frame_count = 0
        self._fps_last = time.perf_counter()
        self._log = get_logger()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.set_target_fps(self._target_fps)
        self.timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.timer.stop()
        self._stop_dxcam()
        self._stop_wgc()
        self._blob_executor.shutdown(wait=False, cancel_futures=True)
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
            self._stack.setCurrentWidget(self._gpu_container)
        else:
            self._stack.setCurrentWidget(self.label)
        self._clear_blob_overlay()

    def set_capture_client_area(self, enabled: bool) -> None:
        self._capture_client = bool(enabled)

    def set_dxcam_async(self, enabled: bool) -> None:
        self._dxcam_async = bool(enabled)
        if self._capture_backend == "dxcam":
            if self._dxcam_async:
                self._restart_dxcam()
            else:
                self._stop_dxcam()

    def set_blob_params(self, params: dict) -> None:
        self._blob_params.update(params)
        self._blob_reset = True
        self._blob_last_submit = 0.0
        self._blob_overlay_pixmap = None
        if not self._blob_params.get("enabled"):
            self._blob_prev = None
            self._blob_bg = None
            self._blob_last_boxes = []
            self._blob_last_mask = None
            self._blob_skip_count = 0
            if self._blob_future and not self._blob_future.done():
                self._blob_future.cancel()
            self._blob_future = None
            self._blob_pending = None
            self._clear_blob_overlay()

    def set_crop(self, left: int, top: int, right: int, bottom: int) -> None:
        self._crop_left = max(0, int(left))
        self._crop_top = max(0, int(top))
        self._crop_right = max(0, int(right))
        self._crop_bottom = max(0, int(bottom))

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
        if backend == "opencv" and not OPENCV_AVAILABLE:
            return
        if backend not in ("numpy", "opencv", "auto"):
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
                self.label.setText("Rognage invalide ou fenetre hors ecran.")
                return

            frame, f_width, f_height = self._grab_frame(left, top, right, bottom, width, height)
            if frame is None:
                return

            blob_enabled = self._blob_params.get("enabled")
            if blob_enabled:
                self._schedule_blob(frame, f_width, f_height)

            use_gpu = self._use_gpu and self._gpu_available
            if use_gpu:
                data, out_w, out_h = self._frame_to_gpu_bytes(frame, f_width, f_height)
                if data is None:
                    return
                self._present_gpu_frame(data, out_w, out_h)
                if blob_enabled:
                    self._update_gpu_overlay(f_width, f_height)
                else:
                    self._clear_blob_overlay()
            else:
                pixmap = self._frame_to_pixmap(frame, f_width, f_height)
                if pixmap is None:
                    return
                pixmap = self._apply_blob_overlay(pixmap, f_width, f_height)
                self._present_pixmap(pixmap)
                self._clear_blob_overlay()
            self._tick_fps()
        except Exception as exc:  # pragma: no cover - UI feedback only
            self._log.exception("update_frame failed")
            self.label.setText(f"Erreur de capture: {exc}")

    def _init_capture_backend(self) -> None:
        if self._capture_backend == "dxcam" and DXCAM_AVAILABLE:
            self._ensure_dxcam_instance()
        else:
            self._dxcam = None

    def _ensure_dxcam_instance(self) -> None:
        if not DXCAM_AVAILABLE:
            self._dxcam = None
            self._dxcam_output_idx = None
            self._dxcam_output_rect = None
            return
        output_idx, output_rect = self._get_monitor_index()
        if output_rect is None:
            output_idx = None
        if self._dxcam is None or output_idx != self._dxcam_output_idx:
            self._stop_dxcam()
            try:
                if output_idx is None:
                    self._dxcam = dxcam.create(output_color="BGRA")
                else:
                    self._dxcam = dxcam.create(output_color="BGRA", output_idx=output_idx)
            except Exception:
                self._dxcam = None
                self._dxcam_output_idx = None
                self._dxcam_output_rect = None
                return
        self._dxcam_output_idx = output_idx
        self._dxcam_output_rect = output_rect

    def _log_foreground_fallback(self, backend: str) -> None:
        now = time.perf_counter()
        if now - self._fallback_last_log >= 5.0:
            self._log.info("Foreground fallback: %s", backend)
            self._fallback_last_log = now

    def _get_monitor_index(self):
        rect = win32gui.GetWindowRect(self.hwnd)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        monitors = win32api.EnumDisplayMonitors()
        for idx, (_, _, mrect) in enumerate(monitors):
            if mrect[0] <= cx < mrect[2] and mrect[1] <= cy < mrect[3]:
                return idx, mrect
        if monitors:
            return 0, monitors[0][2]
        return None, None

    def _dxcam_region_from_absolute(self, region):
        if region is None:
            return None
        if self._dxcam_output_rect is None:
            return region
        left, top, right, bottom = region
        mon_left, mon_top, mon_right, mon_bottom = self._dxcam_output_rect
        left = max(left, mon_left)
        top = max(top, mon_top)
        right = min(right, mon_right)
        bottom = min(bottom, mon_bottom)
        if right <= left or bottom <= top:
            return None
        return (left - mon_left, top - mon_top, right - mon_left, bottom - mon_top)

    def _grab_frame(self, left: int, top: int, right: int, bottom: int, width: int, height: int):
        if (
            self._capture_backend == "mss"
            and self._auto_foreground_fallback
            and win32gui.GetForegroundWindow() == self.hwnd
        ):
            region = (left, top, right, bottom)
            if DXCAM_AVAILABLE:
                self._ensure_dxcam_instance()
                region = self._dxcam_region_from_absolute(region)
                if self._dxcam is not None and region is not None:
                    if self._dxcam_async:
                        if self._ensure_dxcam_started(region):
                            frame = self._dxcam.get_latest_frame()
                        else:
                            frame = None
                    else:
                        try:
                            frame = self._dxcam.grab(region=region)
                        except Exception:
                            frame = None
                    if frame is not None:
                        self._log_foreground_fallback("DXCAM")
                        return frame, frame.shape[1], frame.shape[0]
            if WGC_AVAILABLE:
                self._ensure_wgc_started()
                frame = self._wgc.get_latest() if self._wgc else None
                data, w, h = self._coerce_wgc_frame(frame, left, top, right, bottom)
                if data is not None:
                    self._log_foreground_fallback("WGC")
                    return data, w, h

        if self._capture_backend == "wgc" and WGC_AVAILABLE:
            self._ensure_wgc_started()
            frame = self._wgc.get_latest() if self._wgc else None
            return self._coerce_wgc_frame(frame, left, top, right, bottom)
        if self._capture_backend == "dxcam" and DXCAM_AVAILABLE:
            if self._dxcam is None:
                self._ensure_dxcam_instance()
            region = self._dxcam_region_from_absolute((left, top, right, bottom))
            if region is None:
                return None, 0, 0
            if self._dxcam_async:
                if self._ensure_dxcam_started(region):
                    frame = self._dxcam.get_latest_frame() if self._dxcam else None
                else:
                    frame = None
            else:
                try:
                    frame = self._dxcam.grab(region=region)
                except Exception:
                    frame = None
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

    def _ensure_dxcam_started(self, region) -> bool:
        if not self._dxcam:
            return False
        if self._dxcam_started and self._dxcam_region == region:
            return True
        self._stop_dxcam()
        try:
            self._dxcam.start(target_fps=self._target_fps, region=region)
        except TypeError:
            try:
                self._dxcam.start(target_fps=self._target_fps)
            except TypeError:
                self._dxcam.start()
        except ValueError as exc:
            now = time.perf_counter()
            if now - self._dxcam_last_error >= 2.0:
                self._log.warning("DXCAM region invalid: %s", exc)
                self._dxcam_last_error = now
            return False
        except Exception as exc:
            now = time.perf_counter()
            if now - self._dxcam_last_error >= 2.0:
                self._log.warning("DXCAM start failed: %s", exc)
                self._dxcam_last_error = now
            return False
        self._dxcam_started = True
        self._dxcam_region = region
        return True

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
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
        else:
            left, top, right, bottom = win32gui.GetClientRect(self.hwnd)
            tl = win32gui.ClientToScreen(self.hwnd, (left, top))
            br = win32gui.ClientToScreen(self.hwnd, (right, bottom))
            left, top, right, bottom = tl[0], tl[1], br[0], br[1]
        left += self._crop_left
        top += self._crop_top
        right -= self._crop_right
        bottom -= self._crop_bottom
        return left, top, right, bottom

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

        if (
            self._brightness == 1.0
            and self._contrast == 1.0
            and out_w == width
            and out_h == height
        ):
            qimage = self._qimage_from_raw(frame, width, height)
            if qimage is not None:
                return QtGui.QPixmap.fromImage(qimage)

        if self._effects_backend in ("numpy", "auto") and NUMPY_AVAILABLE:
            pixmap = self._pixmap_from_numpy(frame, width, height, out_w, out_h, use_fast)
            if pixmap is not None:
                return pixmap

        if self._effects_backend in ("opencv", "auto") and OPENCV_AVAILABLE:
            pixmap = self._pixmap_from_opencv(frame, width, height, out_w, out_h, use_fast)
            if pixmap is not None:
                return pixmap

        return self._pixmap_from_pillow(frame, width, height, out_w, out_h, use_fast)

    def _qimage_from_raw(self, frame, width: int, height: int) -> Optional[QtGui.QImage]:
        if isinstance(frame, mss.base.ScreenShot):
            return QtGui.QImage(
                frame.bgra,
                frame.width,
                frame.height,
                QtGui.QImage.Format_ARGB32,
            ).copy()
        if np is not None and isinstance(frame, np.ndarray):
            if frame.ndim != 3:
                return None
            height, width = frame.shape[0], frame.shape[1]
            if frame.shape[2] >= 4:
                fmt = QtGui.QImage.Format_ARGB32
            elif frame.shape[2] == 3:
                fmt = QtGui.QImage.Format_BGR888
            else:
                return None
            return QtGui.QImage(frame.data, width, height, fmt).copy()
        if isinstance(frame, (bytes, bytearray, memoryview)):
            return QtGui.QImage(
                frame,
                width,
                height,
                QtGui.QImage.Format_ARGB32,
            ).copy()
        return None

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

    def _pixmap_from_opencv(
        self,
        frame,
        width: int,
        height: int,
        out_w: int,
        out_h: int,
        use_fast: bool,
    ) -> Optional[QtGui.QPixmap]:
        if cv2 is None:
            return None

        if isinstance(frame, mss.base.ScreenShot):
            arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape(height, width, 4)
        else:
            if np is None:
                return None
            arr = np.asarray(frame)
            if arr.ndim != 3:
                return None

        if out_w != width or out_h != height:
            interp = cv2.INTER_NEAREST if use_fast else cv2.INTER_LINEAR
            arr = cv2.resize(arr, (out_w, out_h), interpolation=interp)
            height, width = arr.shape[0], arr.shape[1]

        if arr.shape[2] >= 3:
            rgb = arr[:, :, :3].astype(np.float32)
        else:
            return None

        if self._contrast != 1.0:
            rgb = (rgb - 128.0) * self._contrast + 128.0
        if self._brightness != 1.0:
            rgb = rgb * self._brightness
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

        if arr.shape[2] >= 4:
            alpha = arr[:, :, 3:4]
            out = np.concatenate((rgb, alpha), axis=2)
            qimage = QtGui.QImage(
                out.data,
                width,
                height,
                QtGui.QImage.Format_ARGB32,
            ).copy()
        else:
            qimage = QtGui.QImage(
                rgb.data,
                width,
                height,
                QtGui.QImage.Format_BGR888,
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

    def _apply_blob_overlay(self, pixmap: QtGui.QPixmap, width: int, height: int) -> QtGui.QPixmap:
        if not self._blob_params.get("enabled"):
            return pixmap
        boxes = self._blob_last_boxes
        mask = self._blob_last_mask
        if not boxes and not (self._blob_params.get("show_mask") and mask is not None):
            return pixmap

        out = QtGui.QPixmap(pixmap)
        painter = QtGui.QPainter(out)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        scale_x = out.width() / width if width > 0 else 1.0
        scale_y = out.height() / height if height > 0 else 1.0

        if self._blob_params.get("show_mask") and mask is not None:
            mask_img = self._mask_to_image(mask, out.width(), out.height())
            if mask_img is not None:
                painter.setOpacity(0.35)
                painter.drawImage(0, 0, mask_img)
                painter.setOpacity(1.0)

        if self._blob_params.get("show_boxes"):
            color = self._blob_params.get("color", (0, 255, 0))
            pen = QtGui.QPen(QtGui.QColor(*color))
            pen.setWidth(self._blob_params.get("line", 2))
            painter.setPen(pen)
            for x, y, w, h in boxes:
                rx = int(x * scale_x)
                ry = int(y * scale_y)
                rw = max(1, int(w * scale_x))
                rh = max(1, int(h * scale_y))
                painter.drawRect(rx, ry, rw, rh)

        if self._blob_params.get("show_centers"):
            color = self._blob_params.get("color", (0, 255, 0))
            pen = QtGui.QPen(QtGui.QColor(*color))
            pen.setWidth(1)
            painter.setPen(pen)
            for x, y, w, h in boxes:
                cx = int((x + w * 0.5) * scale_x)
                cy = int((y + h * 0.5) * scale_y)
                painter.drawLine(cx - 6, cy, cx + 6, cy)
                painter.drawLine(cx, cy - 6, cx, cy + 6)

        self._draw_blob_links_and_labels(painter, boxes, scale_x, scale_y, 0, 0)

        painter.end()
        return out

    def _update_gpu_overlay(self, frame_w: int, frame_h: int) -> None:
        if not self._blob_params.get("enabled"):
            self._clear_blob_overlay()
            return
        boxes = self._blob_last_boxes
        mask = self._blob_last_mask
        show_mask = self._blob_params.get("show_mask")
        if not boxes and not (show_mask and mask is not None):
            self._clear_blob_overlay()
            return

        view_w = self._gl_view.width()
        view_h = self._gl_view.height()
        if view_w <= 0 or view_h <= 0:
            return

        params = (
            self._blob_result_id,
            view_w,
            view_h,
            frame_w,
            frame_h,
            show_mask,
            self._blob_params.get("show_boxes"),
            self._blob_params.get("show_centers"),
            self._blob_params.get("show_labels"),
            self._blob_params.get("label_size"),
            tuple(self._blob_params.get("label_offset", (6, -6))),
            tuple(self._blob_params.get("label_color", (220, 230, 255))),
            self._blob_params.get("link_enabled"),
            self._blob_params.get("link_max"),
            self._blob_params.get("link_dist"),
            self._blob_params.get("link_width"),
            tuple(self._blob_params.get("link_color", (120, 220, 120))),
            self._blob_params.get("line", 2),
            self._blob_params.get("color", (0, 255, 0)),
        )
        if self._blob_overlay_params == params and self._blob_overlay_pixmap is not None:
            if self._overlay.pixmap() is not self._blob_overlay_pixmap:
                self._overlay.setPixmap(self._blob_overlay_pixmap)
            return

        off_x, off_y, disp_w, disp_h = self._fit_viewport(frame_w, frame_h, view_w, view_h)
        if disp_w <= 0 or disp_h <= 0:
            return

        overlay = QtGui.QPixmap(view_w, view_h)
        overlay.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(overlay)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

        if show_mask and mask is not None:
            mask_img = self._mask_to_image(mask, disp_w, disp_h)
            if mask_img is not None:
                painter.setOpacity(0.35)
                painter.drawImage(off_x, off_y, mask_img)
                painter.setOpacity(1.0)

        if boxes:
            scale_x = disp_w / frame_w if frame_w > 0 else 1.0
            scale_y = disp_h / frame_h if frame_h > 0 else 1.0

            if self._blob_params.get("show_boxes"):
                color = self._blob_params.get("color", (0, 255, 0))
                pen = QtGui.QPen(QtGui.QColor(*color))
                pen.setWidth(self._blob_params.get("line", 2))
                painter.setPen(pen)
                for x, y, w, h in boxes:
                    rx = int(x * scale_x) + off_x
                    ry = int(y * scale_y) + off_y
                    rw = max(1, int(w * scale_x))
                    rh = max(1, int(h * scale_y))
                    painter.drawRect(rx, ry, rw, rh)

            if self._blob_params.get("show_centers"):
                color = self._blob_params.get("color", (0, 255, 0))
                pen = QtGui.QPen(QtGui.QColor(*color))
                pen.setWidth(1)
                painter.setPen(pen)
                for x, y, w, h in boxes:
                    cx = int((x + w * 0.5) * scale_x) + off_x
                    cy = int((y + h * 0.5) * scale_y) + off_y
                    painter.drawLine(cx - 6, cy, cx + 6, cy)
                    painter.drawLine(cx, cy - 6, cx, cy + 6)

            self._draw_blob_links_and_labels(painter, boxes, scale_x, scale_y, off_x, off_y)

        painter.end()
        self._blob_overlay_pixmap = overlay
        self._blob_overlay_params = params
        self._overlay.setPixmap(overlay)

    def _draw_blob_links_and_labels(
        self,
        painter: QtGui.QPainter,
        boxes,
        scale_x: float,
        scale_y: float,
        off_x: int,
        off_y: int,
    ) -> None:
        if not boxes:
            return
        centers = []
        for x, y, w, h in boxes:
            centers.append((x + w * 0.5, y + h * 0.5))

        if self._blob_params.get("link_enabled"):
            link_color = self._blob_params.get("link_color", self._blob_params.get("color", (0, 255, 0)))
            link_width = int(self._blob_params.get("link_width", 1))
            link_max = int(self._blob_params.get("link_max", 1))
            link_dist = float(self._blob_params.get("link_dist", 0))
            pen = QtGui.QPen(QtGui.QColor(*link_color))
            pen.setWidth(max(1, link_width))
            painter.setPen(pen)
            edges = set()
            for i, (cx, cy) in enumerate(centers):
                distances = []
                for j, (cx2, cy2) in enumerate(centers):
                    if i == j:
                        continue
                    dx = cx2 - cx
                    dy = cy2 - cy
                    dist = (dx * dx + dy * dy) ** 0.5
                    if link_dist > 0 and dist > link_dist:
                        continue
                    distances.append((dist, j, cx2, cy2))
                distances.sort(key=lambda v: v[0])
                for dist, j, cx2, cy2 in distances[: max(1, link_max)]:
                    key = (min(i, j), max(i, j))
                    if key in edges:
                        continue
                    edges.add(key)
                    x1 = int(cx * scale_x) + off_x
                    y1 = int(cy * scale_y) + off_y
                    x2 = int(cx2 * scale_x) + off_x
                    y2 = int(cy2 * scale_y) + off_y
                    painter.drawLine(x1, y1, x2, y2)

        if self._blob_params.get("show_labels"):
            label_color = self._blob_params.get("label_color", (220, 230, 255))
            label_size = int(self._blob_params.get("label_size", 10))
            label_offset = self._blob_params.get("label_offset", (6, -6))
            try:
                off_dx = int(label_offset[0])
                off_dy = int(label_offset[1])
            except Exception:
                off_dx, off_dy = 6, -6
            painter.setPen(QtGui.QColor(*label_color))
            font = painter.font()
            font.setPointSize(max(6, label_size))
            painter.setFont(font)
            for x, y, w, h in boxes:
                cx = int(x + w * 0.5)
                cy = int(y + h * 0.5)
                px = int(x * scale_x) + off_x + off_dx
                py = int(y * scale_y) + off_y + off_dy
                painter.drawText(px, py, f"x:{cx} y:{cy}")

    def _fit_viewport(self, frame_w: int, frame_h: int, view_w: int, view_h: int):
        if frame_w <= 0 or frame_h <= 0 or view_w <= 0 or view_h <= 0:
            return 0, 0, view_w, view_h
        aspect_frame = frame_w / frame_h
        aspect_view = view_w / view_h
        if aspect_view > aspect_frame:
            disp_h = view_h
            disp_w = int(disp_h * aspect_frame)
        else:
            disp_w = view_w
            disp_h = int(disp_w / aspect_frame)
        off_x = (view_w - disp_w) // 2
        off_y = (view_h - disp_h) // 2
        return off_x, off_y, disp_w, disp_h

    def _clear_blob_overlay(self) -> None:
        self._overlay.clear()
        self._blob_overlay_pixmap = None
        self._blob_overlay_params = None

    def _mask_to_image(self, mask, out_w: int, out_h: int) -> Optional[QtGui.QImage]:
        if np is None:
            return None
        if mask.ndim != 2:
            return None
        h, w = mask.shape
        if h <= 0 or w <= 0:
            return None
        qimg = QtGui.QImage(mask.data, w, h, QtGui.QImage.Format_Grayscale8).copy()
        if w != out_w or h != out_h:
            qimg = qimg.scaled(out_w, out_h, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.FastTransformation)
        return qimg

    def _schedule_blob(self, frame, width: int, height: int) -> None:
        if not self._blob_params.get("enabled"):
            return
        self._poll_blob_future()
        max_fps = float(self._blob_params.get("max_fps", 0) or 0)
        if max_fps > 0:
            now = time.perf_counter()
            if now - self._blob_last_submit < 1.0 / max_fps:
                return
        if self._blob_future and not self._blob_future.done():
            self._blob_pending = (frame, width, height)
            return
        frame_copy = self._copy_frame_for_blob(frame, width, height)
        if frame_copy is None:
            return
        params = dict(self._blob_params)
        state = self._get_blob_state()
        self._blob_future = self._blob_executor.submit(
            self._compute_blob_boxes_worker,
            frame_copy,
            width,
            height,
            params,
            state,
        )
        self._blob_last_submit = time.perf_counter()

    def _poll_blob_future(self) -> None:
        if not self._blob_future or not self._blob_future.done():
            return
        try:
            boxes, mask, prev, bg, skip_count = self._blob_future.result()
            with self._blob_lock:
                self._blob_prev = prev
                self._blob_bg = bg
                self._blob_skip_count = skip_count
            if boxes is not None:
                self._blob_last_boxes = boxes
            if mask is not None:
                self._blob_last_mask = mask
            self._blob_result_id += 1
        except Exception:
            self._log.exception("blob compute failed")
        finally:
            self._blob_future = None
            if self._blob_pending:
                pending = self._blob_pending
                self._blob_pending = None
                self._schedule_blob(*pending)

    def _get_blob_state(self):
        with self._blob_lock:
            if self._blob_reset:
                self._blob_prev = None
                self._blob_bg = None
                self._blob_skip_count = 0
                self._blob_reset = False
            return self._blob_prev, self._blob_bg, self._blob_skip_count

    def _copy_frame_for_blob(self, frame, width: int, height: int):
        if np is None:
            return None
        arr = self._frame_to_bgra_array(frame, width, height)
        if arr is None:
            return None
        return np.ascontiguousarray(arr)

    def _compute_blob_boxes_worker(self, arr, width: int, height: int, params: dict, state):
        prev, bg, skip_count = state
        boxes, mask, prev, bg, skip_count = self._compute_blob_boxes_data(
            arr,
            width,
            height,
            params,
            prev,
            bg,
            skip_count,
        )
        return boxes, mask, prev, bg, skip_count

    def _compute_blob_boxes_data(
        self,
        arr,
        width: int,
        height: int,
        params: dict,
        prev,
        bg,
        skip_count: int,
    ):
        start = time.perf_counter()
        if not params.get("enabled"):
            return None, None, prev, bg, skip_count

        skip = int(params.get("skip", 0))
        if skip > 0:
            if skip_count < skip:
                skip_count += 1
                return None, None, prev, bg, skip_count
            skip_count = 0

        scale = max(0.1, params.get("scale", 50) / 100.0)
        if scale < 1.0 and cv2 is not None:
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            arr = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        elif scale < 1.0 and np is not None:
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            y_idx = (np.linspace(0, arr.shape[0] - 1, new_h)).astype(np.int32)
            x_idx = (np.linspace(0, arr.shape[1] - 1, new_w)).astype(np.int32)
            arr = arr[y_idx[:, None], x_idx]

        gray = None
        if cv2 is not None:
            gray = cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY) if arr.shape[2] == 4 else cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        elif np is not None:
            if arr.shape[2] >= 3:
                gray = (0.114 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.299 * arr[:, :, 2]).astype(np.uint8)
        if gray is None:
            return None, None, prev, bg, skip_count

        alpha = float(params.get("alpha", 0.0))
        if alpha > 0.0:
            if bg is None or bg.shape != gray.shape:
                bg = gray.astype(np.float32)
            else:
                bg = (1.0 - alpha) * bg + alpha * gray
            diff = cv2.absdiff(gray, bg.astype(np.uint8)) if cv2 is not None else np.abs(gray.astype(np.int16) - bg.astype(np.int16)).astype(np.uint8)
        else:
            if prev is None or prev.shape != gray.shape:
                prev = gray
                return None, None, prev, bg, skip_count
            diff = cv2.absdiff(gray, prev) if cv2 is not None else np.abs(gray.astype(np.int16) - prev.astype(np.int16)).astype(np.uint8)
            prev = gray

        blur = int(params.get("blur", 0))
        if blur > 0 and cv2 is not None:
            if blur % 2 == 0:
                blur += 1
            diff = cv2.GaussianBlur(diff, (blur, blur), 0)

        thresh = int(params.get("threshold", 25))
        if cv2 is not None:
            _, mask = cv2.threshold(diff, thresh, 255, cv2.THRESH_BINARY)
        else:
            mask = (diff > thresh).astype(np.uint8) * 255

        erode = int(params.get("erode", 0))
        dilate = int(params.get("dilate", 0))
        if cv2 is not None and (erode > 0 or dilate > 0):
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            if erode > 0:
                mask = cv2.erode(mask, kernel, iterations=erode)
            if dilate > 0:
                mask = cv2.dilate(mask, kernel, iterations=dilate)

        boxes = []
        if cv2 is not None:
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < params.get("min_area", 0):
                    continue
                max_area = params.get("max_area", 0)
                if max_area > 0 and area > max_area:
                    continue
                x, y, w, h = cv2.boundingRect(cnt)
                if w < params.get("min_w", 0) or h < params.get("min_h", 0):
                    continue
                max_w = params.get("max_w", 0)
                max_h = params.get("max_h", 0)
                if max_w > 0 and w > max_w:
                    continue
                if max_h > 0 and h > max_h:
                    continue
                boxes.append((x, y, w, h, area))
        else:
            ys, xs = np.where(mask > 0)
            if xs.size > 0:
                x0, x1 = xs.min(), xs.max()
                y0, y1 = ys.min(), ys.max()
                w = x1 - x0 + 1
                h = y1 - y0 + 1
                max_w = params.get("max_w", 0)
                max_h = params.get("max_h", 0)
                if max_w > 0 and w > max_w:
                    return [], mask, prev, bg, skip_count
                if max_h > 0 and h > max_h:
                    return [], mask, prev, bg, skip_count
                area = w * h
                boxes.append((x0, y0, w, h, area))

        boxes.sort(key=lambda b: b[4], reverse=True)
        max_blobs = int(params.get("max_blobs", 10))
        boxes = boxes[:max_blobs]

        if scale < 1.0:
            inv = 1.0 / scale
            boxes = [(int(x * inv), int(y * inv), int(w * inv), int(h * inv)) for x, y, w, h, _ in boxes]
        else:
            boxes = [(x, y, w, h) for x, y, w, h, _ in boxes]

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if elapsed_ms > 80:
            self._log.warning("blob slow: %.1f ms", elapsed_ms)
        return boxes, mask, prev, bg, skip_count

    def _frame_to_bgra_array(self, frame, width: int, height: int):
        if np is None:
            return None
        if isinstance(frame, mss.base.ScreenShot):
            arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape(height, width, 4)
            return arr
        if isinstance(frame, (bytes, bytearray, memoryview)):
            arr = np.frombuffer(frame, dtype=np.uint8)
            if arr.size == width * height * 4:
                return arr.reshape(height, width, 4)
            return None
        if isinstance(frame, np.ndarray):
            return frame
        return None

    def _tick_fps(self) -> None:
        self._frame_count += 1
        now = time.perf_counter()
        elapsed = now - self._fps_last
        if elapsed >= 1.0:
            fps = self._frame_count / elapsed
            self.fps_updated.emit(fps)
            self._frame_count = 0
            self._fps_last = now
