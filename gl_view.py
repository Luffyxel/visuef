from array import array
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from PyQt5.QtGui import QOpenGLFunctions
except Exception:  # pragma: no cover - fallback for older PyQt5
    try:
        from PyQt5.QtGui import QOpenGLFunctions_2_0 as QOpenGLFunctions
    except Exception:  # pragma: no cover - OpenGL not available
        QOpenGLFunctions = None

try:
    from OpenGL import GL as gl
except Exception:  # pragma: no cover - optional dependency
    gl = None


GL_AVAILABLE = (QOpenGLFunctions is not None) or (gl is not None)

GL_COLOR_BUFFER_BIT = 0x00004000
GL_TRIANGLE_STRIP = 0x0005
GL_FLOAT = 0x1406
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_LINEAR = 0x2601
GL_NEAREST = 0x2600
GL_RGBA = 0x1908
GL_BGRA = 0x80E1
GL_UNSIGNED_BYTE = 0x1401
GL_UNPACK_ALIGNMENT = 0x0CF5


VERTEX_SRC = """
#version 120
attribute vec2 a_pos;
attribute vec2 a_uv;
varying vec2 v_uv;
void main() {
    v_uv = a_uv;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""


FRAG_SRC = """
#version 120
uniform sampler2D u_texture;
uniform float u_brightness;
uniform float u_contrast;
varying vec2 v_uv;
void main() {
    vec4 color = texture2D(u_texture, v_uv);
    color.rgb = (color.rgb - 0.5) * u_contrast + 0.5;
    color.rgb *= u_brightness;
    color.rgb = clamp(color.rgb, 0.0, 1.0);
    gl_FragColor = vec4(color.rgb, 1.0);
}
"""


if GL_AVAILABLE:
    _BaseGL = QOpenGLFunctions if QOpenGLFunctions is not None else object

    class GLFrameView(QtWidgets.QOpenGLWidget, _BaseGL):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._program: Optional[QtGui.QOpenGLShaderProgram] = None
            self._vbo = QtGui.QOpenGLBuffer(QtGui.QOpenGLBuffer.VertexBuffer)
            self._vao = QtGui.QOpenGLVertexArrayObject()
            self._texture_id: Optional[int] = None
            self._texture_size: Optional[tuple[int, int]] = None
            self._gl = None
            self._use_qt_gl = QOpenGLFunctions is not None

            self._frame_data: Optional[bytes] = None
            self._frame_w = 0
            self._frame_h = 0
            self._brightness = 1.0
            self._contrast = 1.0
            self._fast_mode = False

        def set_effects(self, brightness: float, contrast: float) -> None:
            self._brightness = brightness
            self._contrast = contrast
            self.update()

        def set_fast_mode(self, enabled: bool) -> None:
            self._fast_mode = bool(enabled)
            self.update()

        def set_frame(self, data: bytes, width: int, height: int) -> None:
            self._frame_data = data
            self._frame_w = width
            self._frame_h = height
            self.update()

        def initializeGL(self) -> None:
            if self._use_qt_gl:
                self.initializeOpenGLFunctions()
                self._gl = self
            else:
                self._gl = gl
            if self._gl is None:
                return
            self._gl.glClearColor(0.0, 0.0, 0.0, 1.0)
            self._gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)

            self._program = QtGui.QOpenGLShaderProgram()
            self._program.addShaderFromSourceCode(QtGui.QOpenGLShader.Vertex, VERTEX_SRC)
            self._program.addShaderFromSourceCode(QtGui.QOpenGLShader.Fragment, FRAG_SRC)
            self._program.bindAttributeLocation("a_pos", 0)
            self._program.bindAttributeLocation("a_uv", 1)
            self._program.link()

            vertices = array(
                "f",
                [
                    -1.0,
                    -1.0,
                    0.0,
                    1.0,
                    1.0,
                    -1.0,
                    1.0,
                    1.0,
                    -1.0,
                    1.0,
                    0.0,
                    0.0,
                    1.0,
                    1.0,
                    1.0,
                    0.0,
                ],
            )

            self._vao.create()
            self._vao.bind()

            self._vbo.create()
            self._vbo.bind()
            self._vbo.allocate(vertices.tobytes(), len(vertices) * 4)

            self._program.bind()
            self._program.enableAttributeArray(0)
            self._program.setAttributeBuffer(0, GL_FLOAT, 0, 2, 4 * 4)
            self._program.enableAttributeArray(1)
            self._program.setAttributeBuffer(1, GL_FLOAT, 2 * 4, 2, 4 * 4)
            self._program.release()

            self._vbo.release()
            self._vao.release()

            self._texture_id = self._gl.glGenTextures(1)
            self._gl.glBindTexture(GL_TEXTURE_2D, self._texture_id)
            self._apply_texture_filter()
            self._gl.glBindTexture(GL_TEXTURE_2D, 0)

        def resizeGL(self, width: int, height: int) -> None:
            if self._gl is None:
                return
            self._gl.glViewport(0, 0, width, height)

        def paintGL(self) -> None:
            if self._gl is None:
                return
            self._gl.glClear(GL_COLOR_BUFFER_BIT)
            if not self._frame_data or not self._program or not self._texture_id:
                return

            self._apply_viewport()
            self._upload_texture()

            self._gl.glActiveTexture(GL_TEXTURE0)
            self._gl.glBindTexture(GL_TEXTURE_2D, self._texture_id)
            self._apply_texture_filter()

            self._program.bind()
            self._program.setUniformValue("u_texture", 0)
            self._program.setUniformValue("u_brightness", float(self._brightness))
            self._program.setUniformValue("u_contrast", float(self._contrast))

            self._vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            self._vao.release()

            self._program.release()
            self._gl.glBindTexture(GL_TEXTURE_2D, 0)

        def _apply_viewport(self) -> None:
            if self._frame_w <= 0 or self._frame_h <= 0:
                return
            view_w = self.width()
            view_h = self.height()
            if view_w <= 0 or view_h <= 0:
                return

            aspect_frame = self._frame_w / self._frame_h
            aspect_view = view_w / view_h
            if aspect_view > aspect_frame:
                scaled_h = view_h
                scaled_w = int(scaled_h * aspect_frame)
            else:
                scaled_w = view_w
                scaled_h = int(scaled_w / aspect_frame)

            x = (view_w - scaled_w) // 2
            y = (view_h - scaled_h) // 2
            if self._gl is None:
                return
            self._gl.glViewport(x, y, scaled_w, scaled_h)

        def _apply_texture_filter(self) -> None:
            if not self._texture_id or self._gl is None:
                return
            filt = GL_NEAREST if self._fast_mode else GL_LINEAR
            self._gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
            self._gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)

        def _upload_texture(self) -> None:
            if not self._texture_id or self._gl is None:
                return
            w = self._frame_w
            h = self._frame_h
            if w <= 0 or h <= 0:
                return
            self._gl.glBindTexture(GL_TEXTURE_2D, self._texture_id)
            if self._texture_size != (w, h):
                self._gl.glTexImage2D(
                    GL_TEXTURE_2D,
                    0,
                    GL_RGBA,
                    w,
                    h,
                    0,
                    GL_BGRA,
                    GL_UNSIGNED_BYTE,
                    self._frame_data,
                )
                self._texture_size = (w, h)
            else:
                self._gl.glTexSubImage2D(
                    GL_TEXTURE_2D,
                    0,
                    0,
                    0,
                    w,
                    h,
                    GL_BGRA,
                    GL_UNSIGNED_BYTE,
                    self._frame_data,
                )
            self._gl.glBindTexture(GL_TEXTURE_2D, 0)

else:

    class GLFrameView(QtWidgets.QLabel):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAlignment(QtCore.Qt.AlignCenter)
            self.setText("OpenGL indisponible")

        def set_effects(self, brightness: float, contrast: float) -> None:
            return None

        def set_fast_mode(self, enabled: bool) -> None:
            return None

        def set_frame(self, data: bytes, width: int, height: int) -> None:
            return None
