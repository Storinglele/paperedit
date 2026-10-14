"""Regression: replacing one Chinese character must retain unchanged glyph pixels."""
import fitz
import pytest
from pdf_editor.document import DocumentSession, EditError


def predefined_font_document(resource='Original'):
    d = fitz.open()
    p = d.new_page(width=300, height=180)
    # Deliberately nonembedded predefined Unicode CMap, like the reported PDF.
    descriptor = d.get_new_xref()
    d.update_object(descriptor, '<< /Type /FontDescriptor /FontName /STSong-Light /Flags 6 /FontBBox [-25 -254 1000 880] /Ascent 880 /Descent -120 /CapHeight 737 /StemV 58 /ItalicAngle 0 >>')
    descendant = d.get_new_xref()
    d.update_object(descendant, f'<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 /FontDescriptor {descriptor} 0 R >>')
    font = d.get_new_xref()
    d.update_object(font, f'<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light-UniGB-UCS2-H /Encoding /UniGB-UCS2-H /DescendantFonts [{descendant} 0 R] >>')
    d.xref_set_key(p.xref, 'Resources', f'<< /Font << /{resource} {font} 0 R >> >>')
    xref = d.get_new_xref()
    d.update_object(xref, '<<>>')
    text = '转账存入'.encode('utf-16-be').hex()
    d.update_stream(xref, f'BT /{resource} 12 Tf 1 0 0 1 40 120 Tm <{text}> Tj ET\nBT /{resource} 12 Tf 1 0 0 1 40 90 Tm <{text}> Tj ET'.encode())
    p.set_contents(xref)
    return d


def test_predefined_cjk_font_keeps_original_resource_baseline_and_glyph_pixels():
    d = predefined_font_document()
    s = DocumentSession(d.tobytes())
    span = s.spans(0)[0]
    original_image = d[0].get_pixmap(matrix=fitz.Matrix(8, 8), clip=fitz.Rect(40, 45, 75, 65))
    s.replace(0, span, '转账存取', span.size, span.color,
              (span.bbox[0], span.bbox[1], span.bbox[2]+3, span.bbox[3]+5))
    after = fitz.open(stream=s.snapshot(), filetype='pdf')
    changed = next(x for x in s.spans(0) if x.text == '转账存取')
    assert changed.font == 'STSong-Light'
    assert changed.origin == pytest.approx(span.origin, abs=.001)
    assert changed.size == span.size
    assert len(after[0].get_fonts()) == 1
    assert after[0].get_pixmap(matrix=fitz.Matrix(8,8),clip=fitz.Rect(40,45,75,65)).samples == original_image.samples
    assert any(x.text == '转账存入' for x in s.spans(0))


def test_predefined_cjk_font_translation_moves_original_baseline():
    d = predefined_font_document()
    s = DocumentSession(d.tobytes())
    span = s.spans(0)[0]
    s.replace(0, span, '转账存取', span.size, span.color,
              (span.bbox[0]+5, span.bbox[1]+3, span.bbox[2]+8, span.bbox[3]+8))
    changed = next(x for x in s.spans(0) if x.text == '转账存取')
    assert changed.origin == pytest.approx((span.origin[0]+5, span.origin[1]+3), abs=.001)


def test_original_baseline_is_preserved_for_embedded_and_base14_fonts():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((60,100), 'Original text',fontsize=14)
    s = DocumentSession(d.tobytes())
    span=s.spans(0)[0]
    # The properties panel rounds positions to 0.1 pt. It must not shift the baseline.
    s.replace(0,span,'Changed text',14,span.color,(60,round(span.bbox[1],1),250,130))
    changed=next(x for x in s.spans(0) if x.text=='Changed text')
    assert changed.origin==pytest.approx(span.origin, abs=.001)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_native_font_replacement_respects_crop_and_rotation(rotation):
    d = predefined_font_document()
    d[0].set_cropbox(fitz.Rect(20, 10, 250, 160))
    d[0].set_rotation(rotation)
    s = DocumentSession(d.tobytes())
    span = s.spans(0)[0]
    s.replace(0, span, '转账存取', span.size, span.color, fitz.Rect(span.bbox)+(0,0,3,5))
    changed = next(x for x in s.spans(0) if x.text == '转账存取')
    assert changed.origin == pytest.approx(span.origin, abs=.001)


def test_native_font_survives_save_reopen_and_repeated_edits(tmp_path):
    # Resource names containing PDF escapes must remain valid after writing.
    d = predefined_font_document('Original#20Font')
    s = DocumentSession(d.tobytes())
    span = s.spans(0)[0]
    s.replace(0, span, '转账存取', span.size, span.color, fitz.Rect(span.bbox)+(0,0,3,5))
    out = tmp_path/'native.pdf'
    s.save_as(out)
    reopened = DocumentSession.open(out)
    span = next(x for x in reopened.spans(0) if x.text == '转账存取')
    reopened.replace(0, span, '转账存款', span.size, (.2,.3,.4), fitz.Rect(span.bbox)+(0,0,3,5))
    changed = next(x for x in reopened.spans(0) if x.text == '转账存款')
    assert changed.font == 'STSong-Light'
    assert changed.origin == pytest.approx(span.origin, abs=.001)
    assert changed.color == pytest.approx((.2,.3,.4), abs=.005)
    assert len(fitz.open(stream=reopened.snapshot(),filetype='pdf')[0].get_fonts()) == 1


def test_native_font_size_change_preserves_top_edge():
    d = predefined_font_document()
    s = DocumentSession(d.tobytes())
    span = s.spans(0)[0]
    s.replace(0, span, '转账存取', 16, span.color, fitz.Rect(span.bbox)+(0,0,30,10))
    changed = next(x for x in s.spans(0) if x.text == '转账存取')
    assert changed.size == 16
    assert changed.bbox[1] == pytest.approx(span.bbox[1], abs=.001)


@pytest.mark.parametrize('state', ['1 Tc', '80 Tz', '1 Tr', '2 Tr', '0.8 0 0 1 0 0 cm'])
def test_native_font_special_text_state_is_not_silently_discarded(state):
    d = predefined_font_document()
    p = d[0]
    xref = p.get_contents()[0]
    d.update_stream(xref, state.encode()+b'\n'+d.xref_stream(xref))
    s = DocumentSession(d.tobytes())
    before = s.snapshot()
    span = s.spans(0)[0]
    with pytest.raises(EditError):
        s.replace(0, span, '转账存取', span.size, span.color, fitz.Rect(span.bbox)+(0,0,30,5))
    assert s.snapshot() == before


def test_native_same_name_distinct_resources_are_not_guessed():
    d = predefined_font_document()
    p = d[0]
    old = p.get_fonts()[0][0]
    desc = int(d.xref_get_key(old, 'DescendantFonts')[1].split()[0][1:])
    other_desc = d.get_new_xref()
    d.update_object(other_desc, d.xref_object(desc).replace('/DW 1000', '/DW 500'))
    other = d.get_new_xref()
    d.update_object(other, d.xref_object(old).replace(f'{desc} 0 R', f'{other_desc} 0 R'))
    d.xref_set_key(p.xref, 'Resources', f'<< /Font << /Other {other} 0 R /Original {old} 0 R >> >>')
    xref = p.get_contents()[0]
    first, second = d.xref_stream(xref).decode().split('\n')
    d.update_stream(xref, (first+'\n'+second.replace('/Original','/Other')).encode())
    s = DocumentSession(d.tobytes())
    before = s.snapshot()
    span = s.spans(0)[0]
    with pytest.raises(EditError, match='同名'):
        s.replace(0, span, '转账存取', span.size, span.color, fitz.Rect(span.bbox)+(0,0,3,5))
    assert s.snapshot() == before
