"""Generate a public sample with editable bilingual text, image, table and pages."""
from pathlib import Path
import sys
import fitz


def create_pdf(destination):
    with fitz.open() as doc:
        p = doc.new_page(width=595, height=842)
        p.insert_text((60, 80), 'Packaged conversion test', fontsize=18)
        p.insert_text((60, 120), '打包转换测试', fontsize=14, fontname='china-s')
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 40), False)
        pix.clear_with(120)
        p.insert_image((60, 150, 140, 210), pixmap=pix)
        for x in (60, 210, 360):
            p.draw_line((x, 240), (x, 360))
        for y in (240, 300, 360):
            p.draw_line((60, y), (360, y))
        for x, y, text in [(75, 275, 'Item'), (225, 275, 'Amount'),
                           (75, 335, 'Local'), (225, 335, '100')]:
            p.insert_text((x, y), text, fontsize=12)
        doc.new_page(width=595, height=842).insert_text((60, 100), 'Second page', fontsize=14)
        doc.save(destination)


if __name__ == '__main__':
    create_pdf(Path(sys.argv[1]))
