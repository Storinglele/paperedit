"""Render workers open private PDF snapshots and return detached QImages."""
import fitz
from PySide6.QtCore import QObject, Signal, QRunnable
from PySide6.QtGui import QImage
from .document import DocumentSession


class RenderSignals(QObject):
    ready = Signal(int, object, object)
    error = Signal(int, str)


class RenderTask(QRunnable):
    def __init__(self, data, page, scale, revision, token):
        super().__init__()
        self.data, self.page, self.scale = data, page, scale
        self.revision, self.token = revision, token
        self.signals = RenderSignals()

    def run(self):
        try:
            with fitz.open(stream=self.data, filetype='pdf') as doc:
                page = doc[self.page]
                pix = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale), alpha=False)
                image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
                spans = DocumentSession.extract_spans(page, self.revision)
            self.signals.ready.emit(self.token, image, spans)
        except Exception as exc:
            self.signals.error.emit(self.token, str(exc))


class ThumbnailSignals(QObject):
    ready = Signal(int, int, object)
    error = Signal(int, str)


class ThumbnailTask(QRunnable):
    def __init__(self, data, token, page_numbers=None):
        super().__init__()
        self.data, self.token, self.page_numbers = data, token, page_numbers
        self.signals = ThumbnailSignals()

    def run(self):
        try:
            with fitz.open(stream=self.data, filetype='pdf') as doc:
                for number in self.page_numbers if self.page_numbers is not None else range(len(doc)):
                    p = doc[number]
                    scale = min(112 / p.rect.width, 150 / p.rect.height)
                    pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
                    self.signals.ready.emit(self.token, number, image)
        except Exception as exc:
            self.signals.error.emit(self.token, str(exc))
