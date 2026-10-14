"""Write Unicode text through an existing predefined PDF CJK font resource."""
import fitz
from .fonts import font_identity, LayoutError


def validate_native_style(page, target):
    """Admit ordinary filled text; special text states need a richer editor."""
    bi, li, si = map(int, target.key.split(':'))
    span = page.get_text('rawdict')['blocks'][bi]['lines'][li]['spans'][si]
    chars = span['chars']
    reason = '原文字使用特殊字距、缩放或描边效果，暂不支持保持外观的直接编辑。'
    height = (span['ascender'] - span['descender']) * span['size']
    if span.get('alpha', 255) != 255 or any(abs(c['bbox'][3]-c['bbox'][1]-height) > .02 for c in chars):
        raise LayoutError(reason)
    for previous, current in zip(chars, chars[1:]):
        if abs(current['origin'][0] - previous['bbox'][2]) > .02:
            raise LayoutError(reason)
    bounds = fitz.Rect(target.bbox)
    for trace in page.get_texttrace():
        if font_identity(trace['font']) != font_identity(target.font):
            continue
        if not any(bounds.contains(fitz.Point(c[2])) for c in trace['chars']):
            continue
        if trace['type'] != 0 or trace['opacity'] != 1 or trace.get('layer'):
            raise LayoutError(reason)


def pdf_name(name):
    # Encode delimiters as PDF name escapes, never interpolate raw resource names.
    return '/' + ''.join(chr(b) if 33 <= b <= 126 and chr(b) not in '#%()/<>[]{}'
                         else f'#{b:02X}' for b in name.encode('utf-8'))


def insert_native_text(page, lines, resource, encoding, size, color):
    if encoding != 'utf-16-be':
        raise ValueError('不支持此原文字体的编码。')
    if not any(entry[4] == resource and entry[6] == 0 for entry in page.get_fonts(full=True)):
        raise ValueError('原 PDF 字体资源已失效，请重新选择文字。')
    commands = ['q', 'BT', f'{pdf_name(resource)} {size:.9f} Tf',
                '0 Tc 0 Tw 100 Tz 0 Ts 0 Tr',
                ' '.join(f'{v:.9f}' for v in color) + ' rg']
    # PyMuPDF's transformation_matrix omits CropBox offsets when /Rotate is
    # nonzero. Text coordinates are unrotated; read the crop-aware matrix at 0.
    rotation = page.rotation
    try:
        page.set_rotation(0)
        to_pdf = ~page.transformation_matrix
    finally:
        page.set_rotation(rotation)
    for text, baseline in lines:
        if text:
            point = baseline * to_pdf
            commands.append(f'1 0 0 1 {point.x:.9f} {point.y:.9f} Tm')
            commands.append(f'<{text.encode(encoding).hex()}> Tj')
    commands.extend(['ET', 'Q'])
    # Isolate pre-existing graphics transformations from our appended text.
    page.wrap_contents()
    doc = page.parent
    xref = doc.get_new_xref()
    doc.update_object(xref, '<<>>')
    doc.update_stream(xref, '\n'.join(commands).encode('ascii'))
    contents = page.get_contents() + [xref]
    doc.xref_set_key(page.xref, 'Contents', '[' + ' '.join(f'{n} 0 R' for n in contents) + ']')
    # The CMap, rather than a substitute font's glyph table, decides whether
    # each character exists. Reject missing or misencoded characters atomically.
    expected = ''.join(text for text, _ in lines)
    chars = [char for span in page.get_texttrace() for char in span['chars']]
    written = chars[-len(expected):]
    if ''.join(chr(char[0]) for char in written) != expected:
        raise ValueError('原 PDF 字体无法正确显示这些字符，请使用其他文字。')
    bounds = fitz.Rect()
    for char in written:
        bounds |= fitz.Rect(char[3])
    return bounds
