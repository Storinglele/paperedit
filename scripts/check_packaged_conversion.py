"""Smoke-test the frozen app's private PDF-to-Word worker without opening the UI."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import time

import fitz
from docx import Document


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: check_packaged_conversion.py APP_EXECUTABLE')
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='paperedit-packaged-') as tmp:
        root = Path(tmp)
        source = root / 'input.pdf'
        staged = root / 'staged.docx'
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((60, 100), 'Packaged conversion test', fontsize=16)
            page.insert_text((60, 140), '打包转换测试', fontsize=14, fontname='china-s')
            doc.save(source)
        proc = subprocess.Popen([str(executable), '--paperedit-convert-worker', str(root)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        events = []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line:
                event = json.loads(line)
                events.append(event)
                if event.get('type') == 'ready':
                    proc.stdin.write(json.dumps({'type': 'convert', 'staged_path': str(staged)}) + '\n')
                    proc.stdin.flush()
                if event.get('type') in ('complete', 'error'):
                    break
            elif proc.poll() is not None:
                break
        proc.wait(timeout=10)
        if proc.returncode != 0 or not staged.exists():
            raise RuntimeError(f'packaged worker failed: {events!r}; stderr={proc.stderr.read()[-1000:]}')
        text = '\n'.join(p.text for p in Document(staged).paragraphs)
        if 'Packaged conversion test' not in text or '打包转换测试' not in text:
            raise RuntimeError('packaged DOCX is missing editable text')
        print('Packaged conversion passed:', executable)


if __name__ == '__main__':
    main()
