from PyQt5 import QtCore, QtWidgets

from config_store import load_configs, save_configs


class EffectsWindow(QtWidgets.QWidget):
    effects_changed = QtCore.pyqtSignal(float, float)  # brightness, contrast
    fps_changed = QtCore.pyqtSignal(int)
    scale_changed = QtCore.pyqtSignal(int)
    perf_changed = QtCore.pyqtSignal(bool)
    gpu_changed = QtCore.pyqtSignal(bool)
    client_area_changed = QtCore.pyqtSignal(bool)
    dxcam_async_changed = QtCore.pyqtSignal(bool)
    crop_changed = QtCore.pyqtSignal(int, int, int, int)
    blob_changed = QtCore.pyqtSignal(dict)
    backend_changed = QtCore.pyqtSignal(str)
    effects_backend_changed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        has_dxcam: bool,
        has_numpy: bool,
        has_gl: bool,
        has_wgc: bool,
        has_opencv: bool,
    ):
        super().__init__()
        self.setWindowTitle("Reglages (luminosite / contraste)")
        self.setMinimumWidth(380)

        self._configs = load_configs()
        self._loading_profile = False

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_name = QtWidgets.QLineEdit()
        self.profile_name.setPlaceholderText("Nom du profil")
        self.profile_save_btn = QtWidgets.QPushButton("Sauvegarder")
        self.profile_delete_btn = QtWidgets.QPushButton("Supprimer")

        self.brightness_slider = self._make_slider(50, 200, 100)
        self.contrast_slider = self._make_slider(50, 200, 100)
        self.fps_slider = self._make_slider(5, 120, 30)
        self.scale_slider = self._make_slider(10, 100, 100)
        self.fast_checkbox = QtWidgets.QCheckBox("Mode performance")
        self.gpu_checkbox = QtWidgets.QCheckBox("Rendu GPU (OpenGL)")
        self.client_checkbox = QtWidgets.QCheckBox("Zone client")
        self.dxcam_async_checkbox = QtWidgets.QCheckBox("DXCAM async")
        self.crop_left = self._make_spinbox()
        self.crop_top = self._make_spinbox()
        self.crop_right = self._make_spinbox()
        self.crop_bottom = self._make_spinbox()
        self.blob_group = QtWidgets.QGroupBox("Blob tracker")
        self.blob_group.setCheckable(True)
        self.blob_group.setChecked(False)
        self.blob_threshold = self._make_spinbox(0, 255, 25)
        self.blob_min_area = self._make_spinbox(0, 2000000, 600)
        self.blob_max_area = self._make_spinbox(0, 2000000, 0)
        self.blob_min_w = self._make_spinbox(0, 10000, 10)
        self.blob_min_h = self._make_spinbox(0, 10000, 10)
        self.blob_max_w = self._make_spinbox(0, 20000, 0)
        self.blob_max_h = self._make_spinbox(0, 20000, 0)
        self.blob_blur = self._make_spinbox(0, 31, 5)
        self.blob_dilate = self._make_spinbox(0, 10, 2)
        self.blob_erode = self._make_spinbox(0, 10, 0)
        self.blob_scale = self._make_spinbox(10, 100, 50)
        self.blob_max_blobs = self._make_spinbox(1, 100, 10)
        self.blob_skip = self._make_spinbox(0, 30, 0)
        self.blob_fps = self._make_spinbox(1, 120, 15)
        self.blob_alpha = self._make_spinbox(0, 100, 0)
        self.blob_show_boxes = QtWidgets.QCheckBox("Afficher rectangles")
        self.blob_show_centers = QtWidgets.QCheckBox("Afficher centres")
        self.blob_show_mask = QtWidgets.QCheckBox("Afficher masque")
        self.blob_line = self._make_spinbox(1, 10, 2)
        self.blob_r = self._make_spinbox(0, 255, 0)
        self.blob_g = self._make_spinbox(0, 255, 255)
        self.blob_b = self._make_spinbox(0, 255, 0)

        self.backend_combo = QtWidgets.QComboBox()
        self.backend_combo.addItem("MSS", "mss")
        if has_dxcam:
            self.backend_combo.addItem("DXCAM", "dxcam")
        if has_wgc:
            self.backend_combo.addItem("WGC", "wgc")

        self.effects_combo = QtWidgets.QComboBox()
        self.effects_combo.addItem("Auto", "auto")
        if has_numpy:
            self.effects_combo.addItem("NumPy", "numpy")
        if has_opencv:
            self.effects_combo.addItem("OpenCV", "opencv")

        self.fps_value = QtWidgets.QLabel("56")
        self.fps_actual = QtWidgets.QLabel("--")
        self.fps_badge = QtWidgets.QLabel("FPS: --")
        self.fps_badge.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.scale_value = QtWidgets.QLabel("100%")

        rec_form = QtWidgets.QFormLayout()
        rec_form.addRow("Backend capture", self.backend_combo)
        rec_form.addRow("Mode performance", self.fast_checkbox)
        rec_form.addRow("Rendu GPU", self.gpu_checkbox)
        rec_form.addRow("Zone client", self.client_checkbox)
        rec_form.addRow("DXCAM async", self.dxcam_async_checkbox)
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
        rec_form.addRow("FPS cible", fps_container)
        rec_form.addRow("Echelle rendu", scale_container)
        rec_form.addRow("Rognage (px)", self._build_crop_widget())
        rec_form.addRow("FPS reel", self.fps_actual)

        effects_form = QtWidgets.QFormLayout()
        effects_form.addRow("Luminosite", self.brightness_slider)
        effects_form.addRow("Contraste", self.contrast_slider)
        effects_form.addRow("Backend effets", self.effects_combo)
        effects_form.addRow(self._build_blob_group())

        profile_widget = self._build_profile_widget()

        rec_widget = QtWidgets.QWidget()
        rec_widget.setLayout(rec_form)
        effects_widget = QtWidgets.QWidget()
        effects_widget.setLayout(effects_form)

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addStretch(1)
        top_bar.addWidget(self.fps_badge)

        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(top_bar)
        main_layout.addWidget(profile_widget)
        main_layout.addWidget(self._make_section("Rec", rec_widget))
        main_layout.addWidget(self._make_section("Effets", effects_widget))
        self.setLayout(main_layout)

        self._apply_defaults(has_dxcam, has_numpy, has_gl, has_wgc, has_opencv)

        self.brightness_slider.valueChanged.connect(self._emit_effects)
        self.contrast_slider.valueChanged.connect(self._emit_effects)
        self.fps_slider.valueChanged.connect(self._emit_fps)
        self.scale_slider.valueChanged.connect(self._emit_scale)
        self.fast_checkbox.toggled.connect(self._emit_perf)
        self.gpu_checkbox.toggled.connect(self._emit_gpu)
        self.client_checkbox.toggled.connect(self._emit_client)
        self.dxcam_async_checkbox.toggled.connect(self._emit_dxcam_async)
        self.crop_left.valueChanged.connect(self._emit_crop)
        self.crop_top.valueChanged.connect(self._emit_crop)
        self.crop_right.valueChanged.connect(self._emit_crop)
        self.crop_bottom.valueChanged.connect(self._emit_crop)
        self.backend_combo.currentIndexChanged.connect(self._emit_backend)
        self.effects_combo.currentIndexChanged.connect(self._emit_effects_backend)
        self.profile_combo.currentIndexChanged.connect(self._apply_selected_profile)
        self.profile_save_btn.clicked.connect(self._save_profile)
        self.profile_delete_btn.clicked.connect(self._delete_profile)
        self.blob_group.toggled.connect(self._emit_blob)
        self.blob_threshold.valueChanged.connect(self._emit_blob)
        self.blob_min_area.valueChanged.connect(self._emit_blob)
        self.blob_max_area.valueChanged.connect(self._emit_blob)
        self.blob_min_w.valueChanged.connect(self._emit_blob)
        self.blob_min_h.valueChanged.connect(self._emit_blob)
        self.blob_max_w.valueChanged.connect(self._emit_blob)
        self.blob_max_h.valueChanged.connect(self._emit_blob)
        self.blob_blur.valueChanged.connect(self._emit_blob)
        self.blob_dilate.valueChanged.connect(self._emit_blob)
        self.blob_erode.valueChanged.connect(self._emit_blob)
        self.blob_scale.valueChanged.connect(self._emit_blob)
        self.blob_max_blobs.valueChanged.connect(self._emit_blob)
        self.blob_skip.valueChanged.connect(self._emit_blob)
        self.blob_fps.valueChanged.connect(self._emit_blob)
        self.blob_alpha.valueChanged.connect(self._emit_blob)
        self.blob_show_boxes.toggled.connect(self._emit_blob)
        self.blob_show_centers.toggled.connect(self._emit_blob)
        self.blob_show_mask.toggled.connect(self._emit_blob)
        self.blob_line.valueChanged.connect(self._emit_blob)
        self.blob_r.valueChanged.connect(self._emit_blob)
        self.blob_g.valueChanged.connect(self._emit_blob)
        self.blob_b.valueChanged.connect(self._emit_blob)

    def emit_current(self) -> None:
        self._emit_effects()
        self._emit_fps()
        self._emit_scale()
        self._emit_perf()
        self._emit_gpu()
        self._emit_client()
        self._emit_dxcam_async()
        self._emit_crop()
        self._emit_blob()
        self._emit_backend()
        self._emit_effects_backend()

    def _build_profile_widget(self) -> QtWidgets.QWidget:
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Profil"), 0, 0)
        grid.addWidget(self.profile_combo, 0, 1, 1, 2)
        grid.addWidget(self.profile_delete_btn, 0, 3)
        grid.addWidget(QtWidgets.QLabel("Nom"), 1, 0)
        grid.addWidget(self.profile_name, 1, 1, 1, 2)
        grid.addWidget(self.profile_save_btn, 1, 3)
        grid.setContentsMargins(0, 0, 0, 0)

        container = QtWidgets.QWidget()
        container.setLayout(grid)
        self._refresh_profiles()
        return container

    def _make_slider(self, minv: int, maxv: int, val: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(minv, maxv)
        slider.setValue(val)
        slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        slider.setSingleStep(1)
        return slider

    def _make_spinbox(self, minv: int = 0, maxv: int = 10000, val: int = 0) -> QtWidgets.QSpinBox:
        box = QtWidgets.QSpinBox()
        box.setRange(minv, maxv)
        box.setSingleStep(1)
        box.setValue(val)
        return box

    def _build_crop_widget(self) -> QtWidgets.QWidget:
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Gauche"), 0, 0)
        grid.addWidget(self.crop_left, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Haut"), 0, 2)
        grid.addWidget(self.crop_top, 0, 3)
        grid.addWidget(QtWidgets.QLabel("Droite"), 1, 0)
        grid.addWidget(self.crop_right, 1, 1)
        grid.addWidget(QtWidgets.QLabel("Bas"), 1, 2)
        grid.addWidget(self.crop_bottom, 1, 3)
        grid.setContentsMargins(0, 0, 0, 0)
        container = QtWidgets.QWidget()
        container.setLayout(grid)
        return container

    def _build_blob_group(self) -> QtWidgets.QWidget:
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Seuil"), 0, 0)
        grid.addWidget(self.blob_threshold, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Min zone"), 0, 2)
        grid.addWidget(self.blob_min_area, 0, 3)
        grid.addWidget(QtWidgets.QLabel("Max zone"), 1, 0)
        grid.addWidget(self.blob_max_area, 1, 1)
        grid.addWidget(QtWidgets.QLabel("Min L/H"), 1, 2)
        min_size = QtWidgets.QHBoxLayout()
        min_size.addWidget(self.blob_min_w)
        min_size.addWidget(self.blob_min_h)
        min_size_widget = QtWidgets.QWidget()
        min_size_widget.setLayout(min_size)
        grid.addWidget(min_size_widget, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Max L/H"), 2, 0)
        max_size = QtWidgets.QHBoxLayout()
        max_size.addWidget(self.blob_max_w)
        max_size.addWidget(self.blob_max_h)
        max_size_widget = QtWidgets.QWidget()
        max_size_widget.setLayout(max_size)
        grid.addWidget(max_size_widget, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Flou"), 2, 2)
        grid.addWidget(self.blob_blur, 2, 3)
        grid.addWidget(QtWidgets.QLabel("Dilate/Erode"), 3, 0)
        morph = QtWidgets.QHBoxLayout()
        morph.addWidget(self.blob_dilate)
        morph.addWidget(self.blob_erode)
        morph_widget = QtWidgets.QWidget()
        morph_widget.setLayout(morph)
        grid.addWidget(morph_widget, 3, 1)
        grid.addWidget(QtWidgets.QLabel("Echelle %"), 3, 2)
        grid.addWidget(self.blob_scale, 3, 3)
        grid.addWidget(QtWidgets.QLabel("Max blobs"), 4, 0)
        grid.addWidget(self.blob_max_blobs, 4, 1)
        grid.addWidget(QtWidgets.QLabel("Skip frames"), 4, 2)
        grid.addWidget(self.blob_skip, 4, 3)
        grid.addWidget(QtWidgets.QLabel("Lissage %"), 5, 0)
        grid.addWidget(self.blob_alpha, 5, 1)
        grid.addWidget(QtWidgets.QLabel("FPS blob"), 5, 2)
        grid.addWidget(self.blob_fps, 5, 3)
        grid.addWidget(self.blob_show_boxes, 6, 0)
        grid.addWidget(self.blob_show_centers, 6, 1)
        grid.addWidget(self.blob_show_mask, 6, 2)
        grid.addWidget(QtWidgets.QLabel("Epaisseur"), 7, 0)
        grid.addWidget(self.blob_line, 7, 1)
        grid.addWidget(QtWidgets.QLabel("Couleur RGB"), 7, 2)
        colors = QtWidgets.QHBoxLayout()
        colors.addWidget(self.blob_r)
        colors.addWidget(self.blob_g)
        colors.addWidget(self.blob_b)
        colors_widget = QtWidgets.QWidget()
        colors_widget.setLayout(colors)
        grid.addWidget(colors_widget, 7, 3)
        grid.setContentsMargins(4, 4, 4, 4)
        self.blob_group.setLayout(grid)
        return self.blob_group

    def _make_section(self, title: str, content: QtWidgets.QWidget) -> QtWidgets.QWidget:
        toggle = QtWidgets.QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(True)
        toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(QtCore.Qt.DownArrow)

        def on_toggled(checked: bool) -> None:
            toggle.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
            content.setVisible(checked)

        toggle.toggled.connect(on_toggled)
        on_toggled(True)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(toggle)
        layout.addWidget(content)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QtWidgets.QWidget()
        container.setLayout(layout)
        return container

    def _refresh_profiles(self, select_name: str = None) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(aucun)", None)
        for name in sorted(self._configs.keys()):
            self.profile_combo.addItem(name, name)
        if select_name:
            idx = self.profile_combo.findData(select_name)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def _set_combo_data(self, combo: QtWidgets.QComboBox, value: str) -> None:
        if value is None:
            return
        idx = combo.findData(value)
        if idx >= 0:
            old = combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(old)

    def _set_spin_value(self, widget: QtWidgets.QSpinBox, value: int) -> None:
        old = widget.blockSignals(True)
        widget.setValue(int(value))
        widget.blockSignals(old)

    def _set_slider_value(self, widget: QtWidgets.QSlider, value: int) -> None:
        old = widget.blockSignals(True)
        widget.setValue(int(value))
        widget.blockSignals(old)

    def _set_checked(self, widget: QtWidgets.QCheckBox, value: bool) -> None:
        old = widget.blockSignals(True)
        widget.setChecked(bool(value))
        widget.blockSignals(old)

    def _set_group_checked(self, widget: QtWidgets.QGroupBox, value: bool) -> None:
        old = widget.blockSignals(True)
        widget.setChecked(bool(value))
        widget.blockSignals(old)

    def _set_combo_by_data(self, combo: QtWidgets.QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _apply_defaults(
        self,
        has_dxcam: bool,
        has_numpy: bool,
        has_gl: bool,
        has_wgc: bool,
        has_opencv: bool,
    ) -> None:
        self.fps_slider.setValue(56)
        self.scale_slider.setValue(100)
        self.fast_checkbox.setChecked(True)
        self.client_checkbox.setChecked(True)

        self.gpu_checkbox.setEnabled(has_gl)
        if has_gl:
            self.gpu_checkbox.setChecked(True)
        else:
            self.gpu_checkbox.setChecked(False)
            self.gpu_checkbox.setToolTip("OpenGL indisponible dans cette installation PyQt5.")

        self.dxcam_async_checkbox.setEnabled(has_dxcam)
        if has_dxcam:
            self.dxcam_async_checkbox.setChecked(True)
        else:
            self.dxcam_async_checkbox.setChecked(False)
            self.dxcam_async_checkbox.setToolTip("DXCAM non installe.")

        if has_wgc:
            self._set_combo_by_data(self.backend_combo, "wgc")
        elif has_dxcam:
            self._set_combo_by_data(self.backend_combo, "dxcam")
        else:
            self._set_combo_by_data(self.backend_combo, "mss")

        if has_numpy:
            self._set_combo_by_data(self.effects_combo, "numpy")
        elif has_opencv:
            self._set_combo_by_data(self.effects_combo, "opencv")
        else:
            self._set_combo_by_data(self.effects_combo, "auto")

        self._update_fps_value()
        self._update_scale_value()

        self.blob_show_boxes.setChecked(True)
        self.blob_show_centers.setChecked(False)
        self.blob_show_mask.setChecked(False)
        self.blob_fps.setValue(15)
        self.blob_max_w.setValue(0)
        self.blob_max_h.setValue(0)

    def _collect_settings(self) -> dict:
        return {
            "capture_backend": self.backend_combo.currentData(),
            "effects_backend": self.effects_combo.currentData(),
            "brightness": self.brightness_slider.value() / 100.0,
            "contrast": self.contrast_slider.value() / 100.0,
            "fps": self.fps_slider.value(),
            "scale": self.scale_slider.value(),
            "performance": self.fast_checkbox.isChecked(),
            "gpu": self.gpu_checkbox.isChecked(),
            "client_area": self.client_checkbox.isChecked(),
            "dxcam_async": self.dxcam_async_checkbox.isChecked(),
            "crop": {
                "left": self.crop_left.value(),
                "top": self.crop_top.value(),
                "right": self.crop_right.value(),
                "bottom": self.crop_bottom.value(),
            },
            "blob": {
                "enabled": self.blob_group.isChecked(),
                "threshold": self.blob_threshold.value(),
                "min_area": self.blob_min_area.value(),
                "max_area": self.blob_max_area.value(),
                "min_w": self.blob_min_w.value(),
                "min_h": self.blob_min_h.value(),
                "max_w": self.blob_max_w.value(),
                "max_h": self.blob_max_h.value(),
                "blur": self.blob_blur.value(),
                "dilate": self.blob_dilate.value(),
                "erode": self.blob_erode.value(),
                "scale": self.blob_scale.value(),
                "max_blobs": self.blob_max_blobs.value(),
                "skip": self.blob_skip.value(),
                "max_fps": self.blob_fps.value(),
                "alpha": self.blob_alpha.value() / 100.0,
                "show_boxes": self.blob_show_boxes.isChecked(),
                "show_centers": self.blob_show_centers.isChecked(),
                "show_mask": self.blob_show_mask.isChecked(),
                "line": self.blob_line.value(),
                "color": [self.blob_r.value(), self.blob_g.value(), self.blob_b.value()],
            },
        }

    def _apply_settings(self, settings: dict) -> None:
        if not isinstance(settings, dict):
            return

        self._set_combo_data(self.backend_combo, settings.get("capture_backend"))
        self._set_combo_data(self.effects_combo, settings.get("effects_backend"))

        self._set_slider_value(self.brightness_slider, int(round(settings.get("brightness", 1.0) * 100)))
        self._set_slider_value(self.contrast_slider, int(round(settings.get("contrast", 1.0) * 100)))
        self._set_slider_value(self.fps_slider, int(settings.get("fps", self.fps_slider.value())))
        self._set_slider_value(self.scale_slider, int(settings.get("scale", self.scale_slider.value())))

        self._set_checked(self.fast_checkbox, settings.get("performance", self.fast_checkbox.isChecked()))
        self._set_checked(self.gpu_checkbox, settings.get("gpu", self.gpu_checkbox.isChecked()))
        self._set_checked(self.client_checkbox, settings.get("client_area", self.client_checkbox.isChecked()))
        self._set_checked(self.dxcam_async_checkbox, settings.get("dxcam_async", self.dxcam_async_checkbox.isChecked()))

        crop = settings.get("crop", {})
        if isinstance(crop, dict):
            self._set_spin_value(self.crop_left, int(crop.get("left", self.crop_left.value())))
            self._set_spin_value(self.crop_top, int(crop.get("top", self.crop_top.value())))
            self._set_spin_value(self.crop_right, int(crop.get("right", self.crop_right.value())))
            self._set_spin_value(self.crop_bottom, int(crop.get("bottom", self.crop_bottom.value())))

        blob = settings.get("blob", {})
        if isinstance(blob, dict):
            self._set_group_checked(self.blob_group, blob.get("enabled", self.blob_group.isChecked()))
            self._set_spin_value(self.blob_threshold, int(blob.get("threshold", self.blob_threshold.value())))
            self._set_spin_value(self.blob_min_area, int(blob.get("min_area", self.blob_min_area.value())))
            self._set_spin_value(self.blob_max_area, int(blob.get("max_area", self.blob_max_area.value())))
            self._set_spin_value(self.blob_min_w, int(blob.get("min_w", self.blob_min_w.value())))
            self._set_spin_value(self.blob_min_h, int(blob.get("min_h", self.blob_min_h.value())))
            self._set_spin_value(self.blob_max_w, int(blob.get("max_w", self.blob_max_w.value())))
            self._set_spin_value(self.blob_max_h, int(blob.get("max_h", self.blob_max_h.value())))
            self._set_spin_value(self.blob_blur, int(blob.get("blur", self.blob_blur.value())))
            self._set_spin_value(self.blob_dilate, int(blob.get("dilate", self.blob_dilate.value())))
            self._set_spin_value(self.blob_erode, int(blob.get("erode", self.blob_erode.value())))
            self._set_spin_value(self.blob_scale, int(blob.get("scale", self.blob_scale.value())))
            self._set_spin_value(self.blob_max_blobs, int(blob.get("max_blobs", self.blob_max_blobs.value())))
            self._set_spin_value(self.blob_skip, int(blob.get("skip", self.blob_skip.value())))
            self._set_spin_value(self.blob_fps, int(blob.get("max_fps", self.blob_fps.value())))
            self._set_spin_value(self.blob_alpha, int(round(blob.get("alpha", self.blob_alpha.value() / 100.0) * 100)))
            self._set_checked(self.blob_show_boxes, blob.get("show_boxes", self.blob_show_boxes.isChecked()))
            self._set_checked(self.blob_show_centers, blob.get("show_centers", self.blob_show_centers.isChecked()))
            self._set_checked(self.blob_show_mask, blob.get("show_mask", self.blob_show_mask.isChecked()))
            self._set_spin_value(self.blob_line, int(blob.get("line", self.blob_line.value())))
            color = blob.get("color", [self.blob_r.value(), self.blob_g.value(), self.blob_b.value()])
            if isinstance(color, (list, tuple)) and len(color) == 3:
                self._set_spin_value(self.blob_r, int(color[0]))
                self._set_spin_value(self.blob_g, int(color[1]))
                self._set_spin_value(self.blob_b, int(color[2]))

        self.emit_current()

    def _apply_selected_profile(self, _index: int = None) -> None:
        name = self.profile_combo.currentData()
        if not name:
            return
        settings = self._configs.get(name)
        if settings is None:
            return
        self.profile_name.setText(name)
        self._apply_settings(settings)

    def _save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            name = self.profile_combo.currentData() or ""
        if not name:
            QtWidgets.QMessageBox.warning(self, "Erreur", "Nom de profil requis.")
            return
        self._configs[name] = self._collect_settings()
        save_configs(self._configs)
        self._refresh_profiles(select_name=name)
        self.profile_name.setText(name)

    def _delete_profile(self) -> None:
        name = self.profile_combo.currentData()
        if not name:
            return
        if name in self._configs:
            del self._configs[name]
            save_configs(self._configs)
            self._refresh_profiles()
            self.profile_name.setText("")

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

    def _emit_blob(self) -> None:
        params = {
            "enabled": self.blob_group.isChecked(),
            "threshold": self.blob_threshold.value(),
            "min_area": self.blob_min_area.value(),
            "max_area": self.blob_max_area.value(),
            "min_w": self.blob_min_w.value(),
            "min_h": self.blob_min_h.value(),
            "max_w": self.blob_max_w.value(),
            "max_h": self.blob_max_h.value(),
            "blur": self.blob_blur.value(),
            "dilate": self.blob_dilate.value(),
            "erode": self.blob_erode.value(),
            "scale": self.blob_scale.value(),
            "max_blobs": self.blob_max_blobs.value(),
            "skip": self.blob_skip.value(),
            "max_fps": self.blob_fps.value(),
            "alpha": self.blob_alpha.value() / 100.0,
            "show_boxes": self.blob_show_boxes.isChecked(),
            "show_centers": self.blob_show_centers.isChecked(),
            "show_mask": self.blob_show_mask.isChecked(),
            "line": self.blob_line.value(),
            "color": (self.blob_r.value(), self.blob_g.value(), self.blob_b.value()),
        }
        self.blob_changed.emit(params)

    def _emit_crop(self) -> None:
        self.crop_changed.emit(
            self.crop_left.value(),
            self.crop_top.value(),
            self.crop_right.value(),
            self.crop_bottom.value(),
        )

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
        text = f"{fps:.1f}"
        self.fps_actual.setText(text)
        self.fps_badge.setText(f"FPS: {text}")
