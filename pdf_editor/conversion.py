"""Local editable DOCX conversion. Publication is separate from generation."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import zipfile

import fitz


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class ConversionInfo:
    page_count: int
    text_pages: int
    image_only_pages: tuple[int, ...]


def inspect_pdf(data: bytes) -> ConversionInfo:
    try:
        with fitz.open(stream=data, filetype='pdf') as doc:
            if not doc.is_pdf or not len(doc):
                raise ConversionError('文件没有可转换的 PDF 页面。')
            if doc.needs_pass:
                raise ConversionError('请先使用正确密码打开 PDF。')
            text_pages = 0
            image_pages = []
            for page in doc:
                if page.get_text().strip():
                    text_pages += 1
                elif page.get_image_info():
                    image_pages.append(page.number + 1)
            if not text_pages:
                raise ConversionError('文档没有可提取的文字。扫描件需要 OCR，本版暂不支持。')
            return ConversionInfo(len(doc), text_pages, tuple(image_pages))
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError('无法读取此 PDF，请检查文件是否损坏。') from exc


def validate_docx(path: Path) -> None:
    try:
        from docx import Document
        with zipfile.ZipFile(path) as archive:
            required = {'[Content_Types].xml', '_rels/.rels', 'word/document.xml'}
            if not required.issubset(archive.namelist()) or archive.testzip():
                raise ConversionError('生成的 Word 文件校验失败。')
        Document(path)
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError('生成的 Word 文件校验失败。') from exc


def write_docx(data: bytes, staged_path: Path) -> None:
    """Generate a private staged file; never publish a user's destination here."""
    inspect_pdf(data)
    path = Path(staged_path)
    if path.suffix.lower() != '.docx':
        raise ConversionError('请使用 .docx 文件扩展名。')
    converter = None
    previous_logging = logging.root.manager.disable
    try:
        # pdf2docx may log extracted text when reporting a failed page.
        logging.disable(logging.CRITICAL)
        with open(os.devnull, 'w') as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            from pdf2docx import Converter
            converter = Converter(stream=data)
            converter.convert(str(path), ignore_page_error=False, multi_processing=False, ocr=0)
        validate_docx(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, ConversionError):
            raise
        if isinstance(exc, OSError):
            raise ConversionError('无法写入 Word 文件，请检查保存位置和可用空间。') from exc
        raise ConversionError('转换失败，可能包含无法解析的页面或排版。原文件未改动。') from exc
    finally:
        if converter is not None:
            converter.close()
        logging.disable(previous_logging)


def publish_docx(staged_path: Path, destination: Path) -> None:
    """Validate and atomically commit a completed file on the same filesystem."""
    staged_path, destination = Path(staged_path), Path(destination)
    if destination.suffix.lower() != '.docx':
        raise ConversionError('请使用 .docx 文件扩展名，不能覆盖原 PDF。')
    validate_docx(staged_path)
    try:
        with staged_path.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.replace(staged_path, destination)
    except OSError as exc:
        raise ConversionError('无法保存 Word，请检查文件是否被其他程序占用或目录是否可写。') from exc
