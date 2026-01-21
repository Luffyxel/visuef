import sys
from typing import Optional

from PyQt5 import QtWidgets

from effects_window import EffectsWindow
from stream_window import StreamWindow, DXCAM_AVAILABLE, NUMPY_AVAILABLE, OPENCV_AVAILABLE
from gl_view import GL_AVAILABLE
from wgc_capture import WGC_AVAILABLE
from window_utils import list_windows
from logger_utils import setup_logging


class SelectorWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Selection de fenetre a streamer")
        self.setMinimumWidth(420)

        self.combo = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("Rafraichir")
        self.start_btn = QtWidgets.QPushButton("Demarrer le flux")

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel("Choisissez la fenetre a capturer :"))
        layout.addWidget(self.combo)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.refresh_btn)
        buttons.addWidget(self.start_btn)
        layout.addLayout(buttons)

        self.setLayout(layout)

        self.refresh_btn.clicked.connect(self.fill_titles)
        self.start_btn.clicked.connect(self.start_stream)

        self.stream_win: Optional[StreamWindow] = None
        self.effects_win: Optional[EffectsWindow] = None

        self.fill_titles()

    def fill_titles(self) -> None:
        self.combo.clear()
        windows = list_windows()
        if not windows:
            self.combo.addItem("(aucune fenetre detectee)", None)
            return
        for title, hwnd in windows:
            self.combo.addItem(f"{title} (0x{hwnd:08X})", hwnd)

    def start_stream(self) -> None:
        hwnd = self.combo.currentData()
        if not hwnd:
            QtWidgets.QMessageBox.warning(self, "Erreur", "Fenetre introuvable ou non selectionnee.")
            return

        if self.stream_win:
            self.stream_win.close()
        if self.effects_win:
            self.effects_win.close()

        self.stream_win = StreamWindow(hwnd)
        self.effects_win = EffectsWindow(
            DXCAM_AVAILABLE,
            NUMPY_AVAILABLE,
            GL_AVAILABLE,
            WGC_AVAILABLE,
            OPENCV_AVAILABLE,
        )

        self.effects_win.effects_changed.connect(self.stream_win.set_effects)
        self.effects_win.fps_changed.connect(self.stream_win.set_target_fps)
        self.effects_win.scale_changed.connect(self.stream_win.set_scale_percent)
        self.effects_win.perf_changed.connect(self.stream_win.set_fast_mode)
        self.effects_win.gpu_changed.connect(self.stream_win.set_gpu_mode)
        self.effects_win.client_area_changed.connect(self.stream_win.set_capture_client_area)
        self.effects_win.dxcam_async_changed.connect(self.stream_win.set_dxcam_async)
        self.effects_win.crop_changed.connect(self.stream_win.set_crop)
        self.effects_win.blob_changed.connect(self.stream_win.set_blob_params)
        self.effects_win.backend_changed.connect(self.stream_win.set_capture_backend)
        self.effects_win.effects_backend_changed.connect(self.stream_win.set_effects_backend)
        self.stream_win.fps_updated.connect(self.effects_win.set_actual_fps)
        self.stream_win.destroyed.connect(self.effects_win.close)

        self.effects_win.emit_current()
        self.stream_win.show()
        self.effects_win.show()


def main() -> int:
    setup_logging()
    app = QtWidgets.QApplication(sys.argv)
    selector = SelectorWindow()
    selector.show()
    return app.exec()
