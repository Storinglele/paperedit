"""Private subprocess endpoint for DOCX conversion."""
import json
import os
from pathlib import Path
import sys

from .conversion import ConversionError, inspect_pdf, write_docx


def _send(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def worker_main(job_dir: Path) -> int:
    job_dir = Path(job_dir)
    try:
        data = (job_dir / 'input.pdf').read_bytes()
        info = inspect_pdf(data)
        _send({'type': 'ready', 'page_count': info.page_count,
               'text_pages': info.text_pages, 'image_only_pages': list(info.image_only_pages)})
        command = json.loads(sys.stdin.readline())
        if command.get('type') != 'convert':
            raise ConversionError('转换任务指令无效。')
        write_docx(data, Path(command['staged_path']))
        _send({'type': 'complete'})
        return 0
    except Exception as exc:
        _send({'type': 'error', 'message': str(exc) if isinstance(exc, ConversionError) else '转换失败。'})
        return 2

