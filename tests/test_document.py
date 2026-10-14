from pathlib import Path
import fitz
import pytest

from pdf_editor.document import DocumentSession, EditError, PasswordRequired


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / 'source.pdf'
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 100), 'Original wording', fontsize=14)
    page.insert_text((60, 145), 'Neighbour must survive', fontsize=12)
    page.insert_text((60, 200), '原始中文内容', fontsize=16, fontname='china-s')
    page.draw_rect(fitz.Rect(50, 70, 330, 225), color=(0.1, 0.3, 0.8))
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pix.clear_with(150)
    page.insert_image(fitz.Rect(360, 80, 410, 130), pixmap=pix)
    doc.new_page(width=595, height=842).insert_text((60, 100), 'Second page')
    doc.save(path)
    return path


def find(session, text, page=0):
    return next(s for s in session.spans(page) if s.text == text)


def test_replace_removes_original_preserves_neighbours_and_resources(sample, tmp_path):
    before = sample.read_bytes()
    s = DocumentSession.open(sample)
    span = find(s, 'Original wording')
    s.replace(0, span, 'Edited wording', 14, (0, 0, 0), (60, 80, 330, 125))
    output = tmp_path / 'edited.pdf'
    s.save_as(output)
    d = fitz.open(output)
    assert 'Edited wording' in d[0].get_text()
    assert 'Original wording' not in d[0].get_text()
    assert 'Neighbour must survive' in d[0].get_text()
    assert len(d[0].get_images()) == 1
    assert len(d[0].get_drawings()) == 1
    assert sample.read_bytes() == before
    assert not s.dirty


def test_chinese_replacement_is_extractable(sample):
    s = DocumentSession.open(sample)
    s.replace(0, find(s, '原始中文内容'), '中文编辑成功', 16, (0.2, 0.3, 0.5), (60, 175, 330, 220))
    d = fitz.open(stream=s.snapshot(), filetype='pdf')
    assert '中文编辑成功' in d[0].get_text()
    assert '原始中文内容' not in d[0].get_text()


def test_undo_redo_and_saved_state(sample, tmp_path):
    s = DocumentSession.open(sample)
    original = s.snapshot()
    s.add_text(0, 'Added text', 12, (0, 0, 0), (60, 260, 300, 300))
    assert s.dirty
    s.undo()
    assert s.snapshot() == original
    assert not s.dirty
    s.redo()
    assert 'Added text' in fitz.open(stream=s.snapshot(), filetype='pdf')[0].get_text()
    s.save_as(tmp_path / 'saved.pdf')
    s.undo()
    assert s.dirty
    s.redo()
    assert not s.dirty


def test_overflow_is_transactional(sample):
    s = DocumentSession.open(sample)
    before = s.snapshot()
    with pytest.raises(EditError):
        s.replace(0, find(s, 'Original wording'), 'Much too long ' * 30, 20, (0, 0, 0), (60, 80, 90, 100))
    assert s.snapshot() == before
    assert not s.can_undo


def test_overlapping_replacement_rejected(sample):
    s = DocumentSession.open(sample)
    with pytest.raises(EditError):
        s.replace(0, find(s, 'Original wording'), 'Collision', 14, (0, 0, 0), (60, 125, 350, 160))
    assert not s.dirty


def test_stale_span_cannot_replace_wrong_content(sample):
    s = DocumentSession.open(sample)
    stale = find(s, 'Original wording')
    s.add_text(0, 'Changed state', 12, (0, 0, 0), (60, 260, 300, 300))
    with pytest.raises(EditError):
        s.replace(0, stale, 'Oops', 14, (0, 0, 0), (60, 80, 330, 125))


def test_page_rotation_and_text_orientation(sample):
    d = fitz.open(sample)
    d[1].set_rotation(90)
    data = d.tobytes()
    s = DocumentSession(data)
    assert s.page_info(1)['rotation'] == 90
    assert s.page_info(1)['width'] == 842
    assert find(s, 'Second page', 1).editable


def test_existing_redactions_not_applied_as_side_effect(sample):
    d = fitz.open(sample)
    d[0].add_redact_annot((50, 125, 340, 155))
    s = DocumentSession(d.tobytes())
    with pytest.raises(EditError):
        s.replace(0, find(s, 'Original wording'), 'Edited', 14, (0, 0, 0), (60, 80, 330, 125))


def test_password_and_modification_permissions(sample, tmp_path):
    d = fitz.open(sample)
    path = tmp_path / 'encrypted.pdf'
    d.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='reader', permissions=fitz.PDF_PERM_PRINT)
    with pytest.raises(PasswordRequired):
        DocumentSession.open(path)
    s = DocumentSession.open(path, 'reader')
    assert not s.editable
    with pytest.raises(EditError):
        s.add_text(0, 'Forbidden', 12, (0, 0, 0), (60, 260, 300, 300))
    owner = DocumentSession.open(path, 'owner')
    assert owner.editable


def test_source_overwrite_rejected(sample):
    s = DocumentSession.open(sample)
    before = sample.read_bytes()
    with pytest.raises(EditError):
        s.save_as(sample)
    assert sample.read_bytes() == before


def test_invalid_input_does_not_mutate(sample):
    s = DocumentSession.open(sample)
    for text, size, rect in [('text', 0, (60, 260, 300, 300)), ('text', 12, (-20, 260, 300, 300)), ('text', 12, (60, 260, 60, 300))]:
        with pytest.raises(EditError):
            s.add_text(0, text, size, (0, 0, 0), rect)
    assert not s.dirty


def test_userunit_pages_have_true_bounds_and_cannot_be_unsafely_edited(tmp_path):
    d = fitz.open()
    p = d.new_page(width=300, height=300)
    p.insert_text((50, 100), 'Scaled text', fontsize=12)
    d.xref_set_key(p.xref, 'UserUnit', '2')
    s = DocumentSession(d.tobytes())
    assert s.page_info(0)['pdf_width'] == 600
    assert s.page_info(0)['pdf_height'] == 600
    before = s.snapshot()
    with pytest.raises(EditError):
        s.add_text(0, 'Unsafe scaling', 14, (0, 0, 0), (100, 250, 350, 300))
    assert s.snapshot() == before


def test_small_cropbox_preserves_geometry_and_new_text():
    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.insert_text((200, 300), 'Crop text', fontsize=14)
    p.set_cropbox(fitz.Rect(100, 150, 500, 650))
    s = DocumentSession(d.tobytes())
    target = find(s, 'Crop text')
    s.replace(0, target, 'Edited crop', 14, (0, 0, 0), (100, 130, 300, 180))
    result = find(s, 'Edited crop')
    assert result.bbox[0] == pytest.approx(100, abs=.1)
    assert result.bbox[1] == pytest.approx(130, abs=.1)


@pytest.mark.parametrize('text', ['€ – — … œ Œ', 'Ω α β Γ Δ', 'Ж Я Ю'])
def test_unicode_replacement_never_silently_corrupts_text(sample, text):
    s = DocumentSession.open(sample)
    s.replace(0, find(s, 'Original wording'), text, 14, (0, 0, 0), (60, 80, 330, 125))
    assert text in fitz.open(stream=s.snapshot(), filetype='pdf')[0].get_text()


def test_encrypted_export_still_requires_password(sample, tmp_path):
    d = fitz.open(sample)
    path = tmp_path / 'locked.pdf'
    d.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='reader', permissions=fitz.PDF_PERM_PRINT)
    s = DocumentSession.open(path, 'reader')
    output = tmp_path / 'locked-copy.pdf'
    s.save_as(output)
    with fitz.open(output) as check:
        assert check.is_encrypted
        assert check.authenticate('reader')
        assert not (check.permissions & fitz.PDF_PERM_MODIFY)


def test_owner_protected_pdf_without_open_password_keeps_restrictions(sample, tmp_path):
    d = fitz.open(sample)
    path = tmp_path / 'owner-protected.pdf'
    d.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='', permissions=fitz.PDF_PERM_PRINT)
    s = DocumentSession.open(path)
    assert not s.editable
    output = tmp_path / 'protected-copy.pdf'
    s.save_as(output)
    with fitz.open(output) as check:
        assert check.metadata['encryption'] is not None
        assert not (check.permissions & fitz.PDF_PERM_MODIFY)
