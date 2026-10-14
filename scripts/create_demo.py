"""Generate a controlled demo PDF without using personal documents."""
from pathlib import Path
import sys
import fitz

ROOT = Path(__file__).resolve().parents[1]


def build(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    teal = (8/255, 126/255, 131/255)
    dark = (.12, .18, .25)
    page.draw_rect((0, 0, 595, 12), fill=teal, color=teal)
    page.insert_text((48, 73), 'PaperEdit', fontname='hebo', fontsize=30, color=dark)
    page.insert_text((48, 112), 'PDF 编辑体验', fontname='china-s', fontsize=22, color=teal)
    page.insert_text((48, 157), '点击“编辑文字”，再点击下面的句子。', fontname='china-s', fontsize=12, color=dark)
    page.insert_text((48, 207), '这段中文可以直接修改。', fontname='china-s', fontsize=18, color=dark)
    page.insert_text((48, 247), 'You can edit this English sentence.', fontsize=14, color=dark)
    page.insert_text((48, 294), '尝试修改内容、字号和颜色，然后另存为 PDF。', fontname='china-s', fontsize=12, color=dark)
    page.draw_rect((48, 333, 547, 468), color=(.68,.75,.8), width=.6)
    for y in [378, 423]:
        page.draw_line((48,y),(547,y),color=(.68,.75,.8),width=.6)
    page.draw_line((225,333),(225,468),color=(.68,.75,.8),width=.6)
    for x,y,t in [(62,363,'项目'),(240,363,'状态'),(62,408,'中文编辑'),(240,408,'等待你修改'),(62,453,'英文编辑'),(240,453,'可修改原有文字')]:
        page.insert_text((x,y),t,fontname='china-s',fontsize=12,color=dark)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0,0,90,90), False)
    pix.clear_with(200)
    page.insert_image((48,510,138,600),pixmap=pix)
    page.insert_text((158,550),'图片与表格线条保留',fontname='china-s',fontsize=14,color=teal)
    page.insert_text((158,579),'仅替换选中的文字内容',fontname='china-s',fontsize=12,color=dark)
    page.insert_text((48,775),'1 / 3   |   PaperEdit sample',fontsize=10,color=(.4,.46,.52))
    page = doc.new_page(width=595,height=842)
    page.insert_text((48,80),'第二页：添加文字与撤销',fontname='china-s',fontsize=22,color=teal)
    page.insert_text((48,130),'选择“添加文字”，点击空白位置并输入内容。',fontname='china-s',fontsize=13,color=dark)
    page.insert_text((48,170),'使用撤销和重做检查修改，搜索可定位新文字。',fontname='china-s',fontsize=13,color=dark)
    page.draw_rect((48,220,547,700),color=(.7,.76,.8),dashes='[4 4]')
    page.insert_text((48,775),'2 / 3   |   PaperEdit sample',fontsize=10,color=(.4,.46,.52))
    page = doc.new_page(width=595,height=842)
    page.insert_text((60,100),'Rotated page: horizontal text remains editable.',fontsize=14,color=dark)
    page.insert_text((60,160),'旋转页面上的水平文字',fontname='china-s',fontsize=18,color=teal)
    page.set_rotation(90)
    path.parent.mkdir(parents=True,exist_ok=True)
    doc.save(path,garbage=4,deflate=True)
    print(path)


if __name__ == '__main__':
    build(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'artifacts'/'编辑示例.pdf')
