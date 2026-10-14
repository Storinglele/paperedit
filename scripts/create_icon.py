from pathlib import Path
import subprocess
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QPainterPath
from PySide6.QtCore import QRectF, Qt
root=Path(__file__).resolve().parents[1]
iconset=root/'artifacts'/'PaperEdit.iconset'
iconset.mkdir(exist_ok=True)
for size in [16,32,64,128,256,512,1024]:
    image=QImage(size,size,QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size/512,size/512)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#7770F2'))
    p.drawRoundedRect(QRectF(16,16,480,480),108,108)
    p.setBrush(QColor('#FFFFFF'))
    p.drawRoundedRect(QRectF(127,92,245,328),20,20)
    p.setPen(QPen(QColor('#C8C4FF'),14,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    for y in [166,214,262]:p.drawLine(166,y,317,y)
    p.setPen(QPen(QColor('#453CAC'),28,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    p.drawLine(249,357,368,237)
    p.end()
    if size<=512:image.save(str(iconset/f'icon_{size}x{size}.png'))
    if size>=32:
        n=size//2
        image.save(str(iconset/f'icon_{n}x{n}@2x.png'))
subprocess.run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(root/'artifacts'/'PaperEdit.icns')],check=True)
