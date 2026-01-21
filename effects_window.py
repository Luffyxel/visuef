from PyQt5 import QtCore, QtWidgets


class EffectsWindow(QtWidgets.QWidget):
    effects_changed = QtCore.pyqtSignal(float, float)  # brightness, contrast
    fps_changed = QtCore.pyqtSignal(int)
    scale_changed = QtCore.pyqtSignal(int)
    perf_changed = QtCore.pyqtSignal(bool)
    gpu_changed = QtCore.pyqtSignal(bool)
    client_area_changed = QtCore.pyqtSignal(bool)
    dxcam_async_changed = QtCore.pyqtSignal(bool)
    backend_changed = QtCore.pyqtSignal(str)
    effects_backend_changed = QtCore.pyqtSignal(str)

    def __init__(self, has_dxcam: bool, has_numpy: bool, has_gl: bool, has_wgc: bool):
        super().__init__()
        self.setWindowTitle("Reglages (luminosite / contraste)")
        self.setMinimumWidth(380)

        self.brightness_slider = self._make_slider(50, 200, 100)
        self.contrast_slider = self._make_slider(50, 200, 100)
        self.fps_slider = self._make_slider(5, 120, 30)
        self.scale_slider = self._make_slider(10, 100, 100)
        self.fast_checkbox = QtWidgets.QCheckBox("Mode performance")
        self.gpu_checkbox = QtWidgets.QCheckBox("Rendu GPU (OpenGL)")
        self.client_checkbox = QtWidgets.QCheckBox("Zone client")
        self.dxcam_async_checkbox = QtWidgets.QCheckBox("DXCAM async")

        self.backend_combo = QtWidgets.QComboBox()
        self.backend_combo.addItem("MSS", "mss")
        if has_dxcam:
            self.backend_combo.addItem("DXCAM", "dxcam")
        if has_wgc:
            self.backend_combo.addItem("WGC", "wgc")

        self.effects_combo = QtWidgets.QComboBox()
        if has_numpy:
            self.effects_combo.addItem("NumPy", "numpy")
        self.effects_combo.addItem("Pillow", "pillow")

        self.fps_value = QtWidgets.QLabel("30")
        self.fps_actual = QtWidgets.QLabel("--")
        self.scale_value = QtWidgets.QLabel("100%")

        form = QtWidgets.QFormLayout()
        form.addRow("Luminosite", self.brightness_slider)
        form.addRow("Contraste", self.contrast_slider)
        form.addRow("Backend capture", self.backend_combo)
        form.addRow("Backend effets", self.effects_combo)
        form.addRow("Mode performance", self.fast_checkbox)
        form.addRow("Rendu GPU", self.gpu_checkbox)
        form.addRow("Zone client", self.client_checkbox)
        form.addRow("DXCAM async", self.dxcam_async_checkbox)

        fps_layout = QtWidgets.QHBoxLayout()
        fps_layout.addWidget(self.fps_slider)
        fps_layout.addWidget(self.fps_value)
        fps_container = QtWidgets.QWidget()
        fps_container.setLayout(fps_layout)

        scale_layout = QtWidgets.QHBoxLayout()
        scale_layout.addWidget(self.scale_slider)
        scale_layout.addWidget(self.scale_value)
        scale_container = QtWidgets.QWidget()
        scale_container.setLayout(scale_layout)

        form.addRow("FPS cible", fps_container)
        form.addRow("Echelle rendu", scale_container)
        form.addRow("FPS reel", self.fps_actual)
        self.setLayout(form)

        self.brightness_slider.valueChanged.connect(self._emit_effects)
        self.contrast_slider.valueChanged.connect(self._emit_effects)
        self.fps_slider.valueChanged.connect(self._emit_fps)
        self.scale_slider.valueChanged.connect(self._emit_scale)
        self.fast_checkbox.toggled.connect(self._emit_perf)
        self.gpu_checkbox.toggled.connect(self._emit_gpu)
        self.client_checkbox.toggled.connect(self._emit_client)
        self.dxcam_async_checkbox.toggled.connect(self._emit_dxcam_async)
        self.backend_combo.currentIndexChanged.connect(self._emit_backend)
        self.effects_combo.currentIndexChanged.connect(self._emit_effects_backend)

        self.gpu_checkbox.setEnabled(has_gl)
        if not has_gl:
            self.gpu_checkbox.setToolTip("OpenGL indisponible dans cette installation PyQt5.")

        self.dxcam_async_checkbox.setEnabled(has_dxcam)
        if not has_dxcam:
            self.dxcam_async_checkbox.setToolTip("DXCAM non installe.")

        self._update_fps_value()
        self._update_scale_value()

    def emit_current(self) -> None:
        self._emit_effects()
        self._emit_fps()
        self._emit_scale()
        self._emit_perf()
        self._emit_gpu()
        self._emit_client()
        self._emit_dxcam_async()
        self._emit_backend()
        self._emit_effects_backend()

    def _make_slider(self, minv: int, maxv: int, val: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(minv, maxv)
        slider.setValue(val)
        slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        slider.setSingleStep(1)
        return slider

    def _emit_effects(self) -> None:
        brightness = self.brightness_slider.value() / 100.0
        contrast = self.contrast_slider.value() / 100.0
        self.effects_changed.emit(brightness, contrast)

    def _update_fps_value(self) -> None:
        self.fps_value.setText(str(self.fps_slider.value()))

    def _update_scale_value(self) -> None:
        self.scale_value.setText(f"{self.scale_slider.value()}%")

    def _emit_fps(self) -> None:
        self._update_fps_value()
        self.fps_changed.emit(self.fps_slider.value())

    def _emit_scale(self) -> None:
        self._update_scale_value()
        self.scale_changed.emit(self.scale_slider.value())

    def _emit_perf(self) -> None:
        self.perf_changed.emit(self.fast_checkbox.isChecked())

    def _emit_gpu(self) -> None:
        self.gpu_changed.emit(self.gpu_checkbox.isChecked())

    def _emit_client(self) -> None:
        self.client_area_changed.emit(self.client_checkbox.isChecked())

    def _emit_dxcam_async(self) -> None:
        self.dxcam_async_changed.emit(self.dxcam_async_checkbox.isChecked())

    def _emit_backend(self) -> None:
        backend = self.backend_combo.currentData()
        if backend:
            self.backend_changed.emit(backend)

    def _emit_effects_backend(self) -> None:
        backend = self.effects_combo.currentData()
        if backend:
            self.effects_backend_changed.emit(backend)

    @QtCore.pyqtSlot(float)
    def set_actual_fps(self, fps: float) -> None:
        self.fps_actual.setText(f"{fps:.1f}")
