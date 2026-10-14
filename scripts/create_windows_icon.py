"""Create a small Windows ICO without macOS-only icon tooling."""
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "PaperEdit.ico"
OUT.parent.mkdir(exist_ok=True)

size = 256
image = QImage(size, size, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.scale(size / 512, size / 512)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor("#7770F2"))
painter.drawRoundedRect(QRectF(16, 16, 480, 480), 108, 108)
painter.setBrush(QColor("#FFFFFF"))
painter.drawRoundedRect(QRectF(127, 92, 245, 328), 20, 20)
painter.setPen(QPen(QColor("#C8C4FF"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
for y in (166, 214, 262):
    painter.drawLine(166, y, 317, y)
painter.setPen(QPen(QColor("#453CAC"), 28, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
painter.drawLine(249, 357, 368, 237)
painter.end()
if not image.save(str(OUT), "ICO"):
    raise SystemExit(f"unable to write {OUT}")
print(OUT)
