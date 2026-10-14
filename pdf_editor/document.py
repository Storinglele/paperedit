"""Transactional PDF editing. All mutations occur on a private document copy."""
from dataclasses import dataclass
import hashlib
import math
import os
import secrets
from pathlib import Path
import tempfile
import fitz
from .fonts import choose_font, layout_text, LayoutError
from .native_text import insert_native_text, validate_native_style


class EditError(ValueError):
    pass


class PasswordRequired(EditError):
    pass


@dataclass(frozen=True)
class TextSpan:
    key: str
    revision: int
    page: int
    text: str
    bbox: tuple
    origin: tuple
    size: float
    font: str
    color: tuple
    editable: bool
    reason: str = ''


class DocumentSession:
    MAX_HISTORY_BYTES = 256 * 1024 * 1024

    def __init__(self, data: bytes, source: Path | None = None, editable=True):
        with fitz.open(stream=data, filetype='pdf') as doc:
            if not doc.is_pdf or doc.page_count == 0:
                raise EditError('文件没有可阅读的 PDF 页面。')
        self.source = source
        self.editable = editable
        self._history = [data]
        self._index = 0
        self._saved = hashlib.sha256(data).digest()
        self.revision = 0
        self.last_font_note = ''
        self._export_password = None
        self._export_owner_password = None
        self._export_permissions = -1

    @classmethod
    def open(cls, path, password=''):
        path = Path(path).resolve()
        try:
            with fitz.open(path) as doc:
                if not doc.is_pdf:
                    raise EditError('请选择 PDF 文件。')
                auth = 0
                encrypted = doc.xref_get_key(-1, 'Encrypt')[0] != 'null'
                if encrypted:
                    auth = doc.authenticate(password)
                    if not auth:
                        raise PasswordRequired('此 PDF 需要正确的打开密码。')
                editable = bool(auth & 4) or bool(doc.permissions & fitz.PDF_PERM_MODIFY)
                # Working snapshots are decrypted in memory, never written to the source.
                session = cls(doc.tobytes(encryption=fitz.PDF_ENCRYPT_NONE), path, editable)
                if encrypted:
                    session._export_password = password
                    session._export_owner_password = password if auth & 4 else secrets.token_hex(18)
                    session._export_permissions = doc.permissions
                return session
        except PasswordRequired:
            raise
        except (RuntimeError, OSError, ValueError) as exc:
            raise EditError(f'无法打开 PDF：{exc}') from exc

    def snapshot(self):
        return self._history[self._index]

    @property
    def dirty(self):
        return hashlib.sha256(self.snapshot()).digest() != self._saved

    @property
    def can_undo(self):
        return self._index > 0

    @property
    def can_redo(self):
        return self._index < len(self._history) - 1

    @property
    def page_count(self):
        with fitz.open(stream=self.snapshot(), filetype='pdf') as doc:
            return len(doc)

    def page_info(self, number):
        with fitz.open(stream=self.snapshot(), filetype='pdf') as doc:
            p = doc[number]
            return {'width': p.rect.width, 'height': p.rect.height, 'rotation': p.rotation,
                    'pdf_width': (p.rect.height if p.rotation in (90, 270) else p.rect.width),
                    'pdf_height': (p.rect.width if p.rotation in (90, 270) else p.rect.height),
                    'geometry_editable': self.geometry_editable(p)}

    @staticmethod
    def geometry_editable(page):
        unrotated = page.rect * page.derotation_matrix
        return abs(unrotated.width - page.cropbox.width) < .05 and abs(unrotated.height - page.cropbox.height) < .05

    @staticmethod
    def extract_spans(page, revision=0):
        result = []
        for bi, block in enumerate(page.get_text('dict')['blocks']):
            if block['type'] != 0:
                continue
            for li, line in enumerate(block['lines']):
                horizontal = line.get('wmode', 0) == 0 and abs(line['dir'][0] - 1) < .001 and abs(line['dir'][1]) < .001
                for si, span in enumerate(line['spans']):
                    if not span['text'].strip():
                        continue
                    c = span['color']
                    color = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
                    result.append(TextSpan(f'{bi}:{li}:{si}', revision, page.number, span['text'], tuple(span['bbox']),
                                           tuple(span['origin']), span['size'], span['font'], color, horizontal and DocumentSession.geometry_editable(page),
                                           '页面使用特殊缩放单位，暂不支持安全编辑。' if not DocumentSession.geometry_editable(page) else '' if horizontal else '第一版暂不支持竖排或旋转文字的直接编辑。'))
        return result

    def spans(self, number):
        with fitz.open(stream=self.snapshot(), filetype='pdf') as doc:
            return self.extract_spans(doc[number], self.revision)

    def search(self, text):
        if not text.strip():
            return []
        with fitz.open(stream=self.snapshot(), filetype='pdf') as doc:
            return [(p.number, tuple(r)) for p in doc for r in p.search_for(text)]

    def _validate(self, rect, size, color):
        if not self.editable:
            raise EditError('此 PDF 的权限不允许修改。')
        if not math.isfinite(size) or not 1 <= size <= 200:
            raise EditError('字号须为 1–200 pt。')
        if any(not math.isfinite(float(v)) for v in rect):
            raise EditError('文字框位置无效。')
        box = fitz.Rect(rect)
        if box.is_empty or box.is_infinite:
            raise EditError('文字框的宽度和高度必须大于零。')
        if len(color) != 3 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in color):
            raise EditError('文字颜色无效。')
        return box

    def replace(self, number, span, text, size, color, rect):
        if span.revision != self.revision or span.page != number:
            raise EditError('文档已变化，请重新点击要修改的文字。')
        if not span.editable:
            raise EditError(span.reason)
        self._edit(number, text, size, color, rect, span)

    def add_text(self, number, text, size, color, rect):
        if not text.strip():
            raise EditError('请输入要添加的文字。')
        self._edit(number, text, size, color, rect, None)

    def _edit(self, number, text, size, color, rect, target):
        box = self._validate(rect, size, color)
        try:
            with fitz.open(stream=self.snapshot(), filetype='pdf') as doc:
                page = doc[number]
                if not self.geometry_editable(page):
                    raise EditError('页面使用特殊缩放单位，暂不支持安全编辑。')
                bounds = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)
                if not bounds.contains(box):
                    raise EditError('文字框超出页面边界，请调整位置或大小。')
                spans = self.extract_spans(page, self.revision)
                if target and target not in spans:
                    raise EditError('找不到原文字，请重新选择。')
                if target:
                    original = fitz.Rect(target.bbox)
                    for other in spans:
                        if other.key == target.key:
                            continue
                        if original.intersects(fitz.Rect(other.bbox)):
                            raise EditError('原文字与其他文字重叠，无法安全替换。')
                        if text.strip() and box.intersects(fitz.Rect(other.bbox)):
                            raise EditError('新文字框覆盖其他文字，请移动位置或减小编辑框。')
                    annots = list(page.annots() or [])
                    if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in annots):
                        raise EditError('页面含有未应用的涂黑标记，请先在原软件中处理。')
                    if any(original.intersects(fitz.Rect(link['from'])) for link in page.get_links()):
                        raise EditError('原文字包含链接，第一版暂不支持安全替换。')
                font = choose_font(doc, page, target.font if target else None, text)
                if target and font.native_resource:
                    validate_native_style(page, target)
                lines = layout_text(text, size, box, font.font)
                if target and lines and font.preserve_baseline:
                    # The property panel rounds coordinates to 0.1 pt. Preserve
                    # exact original placement when that is the only difference.
                    dx, dy = box.x0 - target.bbox[0], box.y0 - target.bbox[1]
                    dx = 0 if abs(dx) <= .051 else dx
                    dy = 0 if abs(dy) <= .051 else dy
                    baseline = fitz.Point(target.origin[0] + dx,
                                          target.bbox[1] + dy +
                                          (target.origin[1] - target.bbox[1]) * size / target.size)
                    shift = baseline - lines[0][1]
                    lines = [(line, point + shift) for line, point in lines]
                if target:
                    page.add_redact_annot(target.bbox, fill=False, cross_out=False)
                    page.apply_redactions(images=0, graphics=0, text=0)
                if lines:
                    if font.native_resource:
                        written = insert_native_text(page, lines, font.native_resource,
                                                     font.native_encoding, size, color)
                        if not (box + (-.1, -.1, .1, .1)).contains(written):
                            raise EditError('原字体文字超出编辑框，请增加宽度或高度。')
                    elif font.buffer:
                        # A unique resource name avoids reusing a different font on repeated edits.
                        resource = 'PE' + hashlib.sha256(font.buffer).hexdigest()[:12]
                        page.insert_font(fontname=resource, fontbuffer=font.buffer)
                    else:
                        resource = font.name
                    if not font.native_resource:
                        for line, baseline in lines:
                            if line:
                                page.insert_text(baseline, line, fontsize=size, fontname=resource, color=color)
                updated = doc.tobytes(garbage=4, deflate=True)
            self.last_font_note = font.note
            self._commit(updated)
        except EditError:
            raise
        except (RuntimeError, ValueError, IndexError) as exc:
            raise EditError(str(exc)) from exc

    def _commit(self, data):
        self._history = self._history[:self._index + 1] + [data]
        self._index += 1
        while len(self._history) > 2 and sum(map(len, self._history)) > self.MAX_HISTORY_BYTES:
            self._history.pop(0)
            self._index -= 1
        self.revision += 1

    def undo(self):
        if self.can_undo:
            self._index -= 1
            self.revision += 1

    def redo(self):
        if self.can_redo:
            self._index += 1
            self.revision += 1

    def save_as(self, path):
        path = Path(path).expanduser().resolve()
        if self.source and path == self.source:
            raise EditError('请另存到新文件，保留原 PDF。')
        if path.suffix.lower() != '.pdf':
            raise EditError('请使用 .pdf 文件扩展名。')
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(prefix='.paperedit-', suffix='.pdf', dir=path.parent)
            os.close(fd)
            with fitz.open(stream=self.snapshot(), filetype='pdf') as doc:
                doc.subset_fonts()
                options = {}
                if self._export_password is not None:
                    options = dict(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=self._export_password,
                                   owner_pw=self._export_owner_password, permissions=self._export_permissions)
                doc.save(tmp, garbage=4, deflate=True, **options)
            with fitz.open(tmp) as check:
                if check.is_encrypted and not check.authenticate(self._export_password or ''):
                    raise EditError('保存的加密文件验证失败。')
                if len(check) != self.page_count:
                    raise EditError('保存验证失败，原文件未改动。')
            with open(tmp, 'rb') as stream:
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            self._saved = hashlib.sha256(self.snapshot()).digest()
        except (OSError, RuntimeError, ValueError) as exc:
            raise EditError(f'保存失败：{exc}') from exc
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
