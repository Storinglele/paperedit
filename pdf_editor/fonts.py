"""Font selection and bounded text layout, independent of the UI."""
from dataclasses import dataclass
import math
import fitz


class LayoutError(ValueError):
    pass


@dataclass
class FontChoice:
    font: fitz.Font
    buffer: bytes | None
    name: str
    note: str
    native_resource: str | None = None
    native_encoding: str | None = None
    preserve_baseline: bool = False


def font_identity(name):
    """PDF BaseFont names may include subset tags and a CMap suffix."""
    name = name.split('+')[-1]
    for suffix in ['-UniGB-UCS2-H', '-UniGB-UTF16-H', '-UniCNS-UCS2-H', '-UniCNS-UTF16-H',
                   '-UniJIS-UCS2-H', '-UniJIS-UTF16-H', '-UniKS-UCS2-H', '-UniKS-UTF16-H']:
        name = name.removesuffix(suffix)
    return name


class NativeFontMetrics:
    """Measure using advances from the original PDF, without changing its font."""
    def __init__(self, page, original):
        self.name = original
        self.ascender, self.descender = .88, -.12
        self._fallback = fitz.Font('cjk')
        self._widths = {}
        for block in page.get_text('rawdict')['blocks']:
            if block['type'] != 0:
                continue
            for line in block['lines']:
                for span in line['spans']:
                    if font_identity(span['font']) != font_identity(original):
                        continue
                    self.ascender, self.descender = span['ascender'], span['descender']
                    for char in span['chars']:
                        width = (char['bbox'][2] - char['origin'][0]) / span['size']
                        if width > 0:
                            self._widths[char['c']] = width

    def has_glyph(self, codepoint):
        return self._fallback.has_glyph(codepoint)

    def text_length(self, text, fontsize=11):
        return sum(self._widths.get(c, self._fallback.text_length(c, fontsize=1)) for c in text) * fontsize


def choose_font(doc, page, original: str | None, text: str) -> FontChoice:
    def supports(font):
        return all(c in '\n\r\t' or font.has_glyph(ord(c)) for c in text)

    if original:
        matches = [entry for entry in page.get_fonts(full=True)
                   if font_identity(entry[3]) == font_identity(original)]
        for entry in matches:
            xref, _, _, base, resource, encoding, referencer = entry
            if font_identity(base) != font_identity(original):
                continue
            try:
                _, _, _, data = doc.extract_font(xref)
                if data:
                    font = fitz.Font(fontbuffer=data)
                    if supports(font):
                        return FontChoice(font, data, 'PaperEditFont', '使用原文档字体', preserve_baseline=True)
                elif referencer == 0 and encoding in {
                    'UniGB-UCS2-H', 'UniGB-UTF16-H', 'UniCNS-UCS2-H', 'UniCNS-UTF16-H',
                    'UniJIS-UCS2-H', 'UniJIS-UTF16-H', 'UniKS-UCS2-H', 'UniKS-UTF16-H',
                }:
                    if len({entry[0] for entry in matches}) > 1:
                        raise LayoutError('页面有多个同名字体资源，暂时无法安全确定原字体。')
                    metrics = NativeFontMetrics(page, original)
                    if supports(metrics) and ('UTF16' in encoding or all(ord(c) <= 0xFFFF for c in text)):
                        return FontChoice(metrics, None, resource, '沿用原 PDF 字体：' + original,
                                          resource, 'utf-16-be', preserve_baseline=True)
            except LayoutError:
                raise
            except (RuntimeError, ValueError):
                pass
        aliases = {
            'Helvetica': 'helv', 'Helvetica-Bold': 'hebo', 'Helvetica-Oblique': 'heit',
            'Helvetica-BoldOblique': 'hebi', 'Times-Roman': 'tiro', 'Times-Bold': 'tibo',
            'Times-Italic': 'tiit', 'Times-BoldItalic': 'tibi', 'Courier': 'cour',
            'Courier-Bold': 'cobo', 'Courier-Oblique': 'coit', 'Courier-BoldOblique': 'cobi',
        }
        name = aliases.get(original)
        if name:
            font = fitz.Font(name)
            if supports(font):
                return FontChoice(font, font.buffer, name, '使用原文档字体', preserve_baseline=True)
    latin = fitz.Font('helv')
    if supports(latin):
        return FontChoice(latin, latin.buffer, 'helv', '替代字体：Helvetica' if original else 'Helvetica')
    cjk = fitz.Font('cjk')
    if not supports(cjk):
        raise LayoutError('字体无法显示部分字符，请移除特殊字符或使用其他文字。')
    return FontChoice(cjk, cjk.buffer, 'PaperEditCJK', '替代字体：Droid Sans Fallback（支持中文）' if original else 'Droid Sans Fallback（支持中文）')


def layout_text(text: str, size: float, rect: fitz.Rect, font: fitz.Font):
    if not text.strip():
        return []
    lines = []
    for paragraph in text.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4).split('\n'):
        line = ''
        for char in paragraph:
            if font.text_length(char, fontsize=size) > rect.width + .01:
                raise LayoutError('文字框太窄，请增加宽度或减小字号。')
            if line and font.text_length(line + char, fontsize=size) > rect.width + .01:
                lines.append(line)
                line = char
            else:
                line += char
        lines.append(line)
    ascent = max(font.ascender, .8)
    descent = min(font.descender, -.1)
    line_height = max(ascent - descent, 1.35) * size
    needed = (ascent - descent) * size + max(0, len(lines) - 1) * line_height
    if needed > rect.height + .1:
        raise LayoutError(f'文字超出编辑框（需要高度约 {math.ceil(needed)} pt），请增加高度或减小字号。')
    return [(line, fitz.Point(rect.x0, rect.y0 + ascent * size + i * line_height)) for i, line in enumerate(lines)]
