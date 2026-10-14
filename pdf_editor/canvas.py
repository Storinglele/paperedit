"""Page image with PDF-space hit testing and selection overlays."""
import fitz
import sys
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QImage, QFont, QFontDatabase
from PySide6.QtWidgets import QWidget, QPlainTextEdit, QPushButton, QHBoxLayout


class InlineEditor(QPlainTextEdit):
    commit = Signal()
    cancel = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.commit.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class DragHandle(QWidget):
    def __init__(self, canvas, mode):
        super().__init__(canvas)
        self.mode = mode
        self.setStyleSheet('background: #7770F2; border: 1px solid white; border-radius: 2px;')
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if mode == 'resize' else Qt.CursorShape.SizeAllCursor)
        self.setAccessibleName('调整文字框大小' if mode == 'resize' else '移动文字框')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.hide()

    def mousePressEvent(self, event):
        canvas = self.parentWidget()
        box = canvas.selected.bbox if hasattr(canvas.selected, 'bbox') else canvas.selected
        point = canvas.to_pdf(canvas.mapFromGlobal(event.globalPosition().toPoint()))
        canvas._dragging = (self.mode, fitz.Rect(box), point)
        event.accept()

    def mouseMoveEvent(self, event):
        canvas = self.parentWidget()
        point = canvas.to_pdf(canvas.mapFromGlobal(event.globalPosition().toPoint()))
        canvas.drag_to(point)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.parentWidget()._dragging = None
        event.accept()


class PageCanvas(QWidget):
    span_selected = Signal(object)
    add_requested = Signal(float, float)
    inline_changed = Signal(str)
    commit_requested = Signal()
    cancel_requested = Signal()
    rect_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.spans = []
        self.search_rects = []
        self.selected = None
        self.mode = 'read'
        self.scale = 1.0
        self.rotation = 0
        self.pdf_width = 595
        self.pdf_height = 842
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(595, 842)
        self.setAccessibleName('PDF 页面')
        self.inline_editor = InlineEditor(self)
        self.inline_editor.setAccessibleName('直接编辑页面文字')
        self.inline_editor.setStyleSheet('QPlainTextEdit { background: white; border: 2px solid #7770F2; border-radius: 0; padding: 0px; color: #263445; }')
        self.inline_editor.document().setDocumentMargin(0)
        self.inline_editor.textChanged.connect(lambda: self.inline_changed.emit(self.inline_editor.toPlainText()))
        self.inline_editor.commit.connect(self.commit_requested)
        self.inline_editor.cancel.connect(self.cancel_requested)
        self.inline_editor.hide()
        self.edit_bar = QWidget(self)
        self.edit_bar.setStyleSheet('background: #FFFFFF; border-radius: 5px;')
        bar = QHBoxLayout(self.edit_bar)
        bar.setContentsMargins(4, 3, 4, 3)
        commit = QPushButton('完成编辑')
        commit.setToolTip('⌘Enter / Ctrl+Enter')
        cancel = QPushButton('取消')
        commit.clicked.connect(self.commit_requested)
        cancel.clicked.connect(self.cancel_requested)
        bar.addWidget(commit)
        bar.addWidget(cancel)
        self.edit_bar.hide()
        self._dragging = None
        self._font_ids = {}
        self.resize_handle = DragHandle(self, 'resize')
        self.move_handle = DragHandle(self, 'move')

    def configure_geometry(self, width, height, rotation, scale):
        self.pdf_width, self.pdf_height = width, height
        self.rotation, self.scale = rotation, scale
        bounds = fitz.Rect(0, 0, width, height) * fitz.Matrix(rotation)
        self.setFixedSize(round(bounds.width * scale), round(bounds.height * scale))

    def _matrix(self):
        return {
            0: fitz.Matrix(1, 0, 0, 1, 0, 0),
            90: fitz.Matrix(0, 1, -1, 0, self.pdf_height, 0),
            180: fitz.Matrix(-1, 0, 0, -1, self.pdf_width, self.pdf_height),
            270: fitz.Matrix(0, -1, 1, 0, 0, self.pdf_width),
        }[self.rotation]

    def to_pdf(self, position):
        return fitz.Point(position.x() / self.scale, position.y() / self.scale) * ~self._matrix()

    def display_rect(self, box):
        r = fitz.Rect(box) * self._matrix()
        return QRectF(r.x0 * self.scale, r.y0 * self.scale, r.width * self.scale, r.height * self.scale)

    def set_page(self, image, spans):
        self.image = image
        self.spans = spans
        self.selected = None
        self.update()

    def show_editor(self, text, box, size, color, font_buffer=None):
        self.inline_editor.blockSignals(True)
        self.inline_editor.setPlainText(text)
        self.inline_editor.blockSignals(False)
        family = 'Microsoft YaHei' if sys.platform == 'win32' else 'PingFang SC'
        if font_buffer:
            key = hash(font_buffer)
            if key not in self._font_ids:
                self._font_ids[key] = QFontDatabase.addApplicationFontFromData(font_buffer)
            families = QFontDatabase.applicationFontFamilies(self._font_ids[key])
            if families:
                family = families[0]
        font = QFont(family)
        font.setPixelSize(max(6, round(size * self.scale)))
        self.inline_editor.setFont(font)
        self.inline_editor.setStyleSheet(f'QPlainTextEdit {{ background: white; border: 2px solid #7770F2; border-radius: 0; padding: 0; color: {QColor.fromRgbF(*color).name()}; }}')
        self.position_editor(box)
        self.inline_editor.show()
        self.edit_bar.show()
        self.inline_editor.raise_()
        self.edit_bar.raise_()
        self.resize_handle.show()
        self.move_handle.show()
        self.resize_handle.raise_()
        self.move_handle.raise_()
        self.inline_editor.setFocus()
        self.inline_editor.selectAll()

    def position_editor(self, box):
        r = self.display_rect(box)
        # Keep rotated-page editing readable; coordinates remain PDF-space.
        self.inline_editor.setGeometry(round(r.x()), round(r.y()), max(35, round(r.width())), max(24, round(r.height())))
        self.edit_bar.adjustSize()
        self.edit_bar.move(max(0, min(round(r.x()), self.width() - self.edit_bar.width())),
                           max(0, min(round(r.bottom()) + 7, self.height() - self.edit_bar.height())))
        self.selected = box
        self.resize_handle.setGeometry(round(r.right()) - 5, round(r.bottom()) - 5, 10, 10)
        self.move_handle.setGeometry(round(r.center().x()) - 12, round(r.top()) - 5, 24, 8)
        self.resize_handle.raise_()
        self.move_handle.raise_()
        self.update()

    def hide_editor(self):
        self.inline_editor.hide()
        self.edit_bar.hide()
        self.resize_handle.hide()
        self.move_handle.hide()

    def clear_page(self):
        self.hide_editor()
        self.image = QImage()
        self.spans = []
        self.selected = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        if not self.image.isNull():
            painter.drawImage(self.rect(), self.image)
        if self.mode == 'edit':
            painter.setPen(QPen(QColor('#7770F260'), 1, Qt.PenStyle.DashLine))
            for s in self.spans:
                if s.editable:
                    painter.drawRect(self.display_rect(s.bbox))
        for r in self.search_rects:
            painter.fillRect(self.display_rect(r), QColor(255, 208, 64, 90))
        if self.selected:
            box = self.selected.bbox if hasattr(self.selected, 'bbox') else self.selected
            painter.fillRect(self.display_rect(box), QColor(8, 126, 131, 25))
            painter.setPen(QPen(QColor('#7770F2'), 2))
            r = self.display_rect(box)
            painter.drawRect(r)
            painter.fillRect(QRectF(r.right() - 4, r.bottom() - 4, 8, 8), QColor('#7770F2'))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.image.isNull():
            return
        point = self.to_pdf(event.position())
        if self.inline_editor.isVisible() and self.selected:
            box = self.selected.bbox if hasattr(self.selected, 'bbox') else self.selected
            r = self.display_rect(box)
            if abs(event.position().x() - r.right()) < 10 and abs(event.position().y() - r.bottom()) < 10:
                self._dragging = ('resize', fitz.Rect(box), point)
                return
            if abs(event.position().y() - r.top()) < 6 and r.left() - 6 <= event.position().x() <= r.right() + 6:
                self._dragging = ('move', fitz.Rect(box), point)
                return
        if self.mode == 'add':
            self.add_requested.emit(point.x, point.y)
        else:
            matches = [s for s in self.spans if fitz.Rect(s.bbox).contains(point)]
            if matches:
                self.span_selected.emit(min(matches, key=lambda s: fitz.Rect(s.bbox).get_area()))

    def mouseReleaseEvent(self, event):
        self._dragging = None

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.drag_to(self.to_pdf(event.position()))
            return
        if self.mode == 'add':
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif any(fitz.Rect(s.bbox).contains(self.to_pdf(event.position())) for s in self.spans):
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def drag_to(self, point):
        if self._dragging:
            mode, original, start = self._dragging
            dx, dy = point.x - start.x, point.y - start.y
            if mode == 'resize':
                box = fitz.Rect(original.x0, original.y0, max(original.x0 + 5, original.x1 + dx), max(original.y0 + 5, original.y1 + dy))
            else:
                box = fitz.Rect(original.x0 + dx, original.y0 + dy, original.x1 + dx, original.y1 + dy)
            if fitz.Rect(0, 0, self.pdf_width, self.pdf_height).contains(box):
                self.rect_changed.emit(tuple(box))
            return
