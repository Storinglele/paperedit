"""Private subprocess endpoint; file protocol works in windowed Windows builds."""
import json
import os
from pathlib import Path
import time

from .conversion import ConversionError, inspect_pdf, write_docx


def write_message(path: Path, payload: dict):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def worker_main(job_dir: Path) -> int:
    job_dir = Path(job_dir)
    from PySide6.QtCore import QLockFile
    lock = QLockFile(str(job_dir / 'worker.lock'))
    if not lock.tryLock(0):
        return 2
    try:
        data = (job_dir / 'input.pdf').read_bytes()
        info = inspect_pdf(data)
        write_message(job_dir / 'ready.json', {'page_count': info.page_count,
                      'text_pages': info.text_pages, 'image_only_pages': list(info.image_only_pages)})
        deadline = time.monotonic() + 1800
        command_path = job_dir / 'command.json'
        while not command_path.exists():
            if not job_dir.exists() or time.monotonic() > deadline:
                return 2
            time.sleep(.05)
        command = json.loads(command_path.read_text(encoding='utf-8'))
        if command.get('type') != 'convert':
            raise ConversionError('转换任务指令无效。')
        write_docx(data, Path(command['staged_path']))
        write_message(job_dir / 'result.json', {'type': 'complete'})
        return 0
    except Exception as exc:
        if job_dir.exists():
            write_message(job_dir / 'result.json', {'type': 'error',
                'message': str(exc) if isinstance(exc, ConversionError) else '转换失败。'})
        return 2
    finally:
        lock.unlock()
