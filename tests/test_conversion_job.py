import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import importlib
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate, timeout=30000):
    for _ in range(timeout // 10):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError('Conversion event did not arrive')


def source_bytes():
    with fitz.open() as doc:
        doc.new_page().insert_text((60, 100), 'Real worker editable text')
        return doc.tobytes()


def job_module():
    return importlib.import_module('pdf_editor.conversion_job')


def test_real_worker_exports_docx(app, tmp_path):
    from docx import Document
    job = job_module().ConversionJob()
    ready, success, errors, finished = [], [], [], []
    job.ready.connect(ready.append)
    job.succeeded.connect(success.append)
    job.failed.connect(errors.append)
    job.finished.connect(lambda: finished.append(True))
    job.start(source_bytes())
    assert job.running
    wait_until(app, lambda: ready or errors)
    assert not errors
    job_dir = job.job_dir
    dest = tmp_path / '实际 输出.docx'
    dest.write_bytes(b'previous')
    job.proceed(dest)
    wait_until(app, lambda: finished)
    assert errors == []
    assert success == [str(dest)]
    assert len(finished) == 1 and not job.running
    assert 'Real worker editable text' in '\n'.join(p.text for p in Document(dest).paragraphs)
    assert not job_dir.exists()
    assert not list(tmp_path.glob('.paperedit-word-*'))


def test_cancel_keeps_existing_destination(app, tmp_path):
    job = job_module().ConversionJob()
    ready, finished, success = [], [], []
    job.ready.connect(ready.append)
    job.finished.connect(lambda: finished.append(True))
    job.succeeded.connect(success.append)
    job.start(source_bytes())
    wait_until(app, lambda: ready)
    job_dir = job.job_dir
    dest = tmp_path / 'existing.docx'
    dest.write_bytes(b'old document')
    job.proceed(dest)
    job.cancel()
    wait_until(app, lambda: finished)
    assert dest.read_bytes() == b'old document'
    assert not success and len(finished) == 1
    assert job.process.state() == QProcess.ProcessState.NotRunning
    assert not job_dir.exists()
    assert not list(tmp_path.glob('.paperedit-word-*'))


def test_invalid_pdf_reports_failure_and_cleans_up(app):
    job = job_module().ConversionJob()
    errors, finished = [], []
    job.failed.connect(errors.append)
    job.finished.connect(lambda: finished.append(True))
    job.start(b'broken pdf')
    job_dir = job.job_dir
    wait_until(app, lambda: finished)
    assert len(errors) == 1 and len(finished) == 1
    assert not job.running and not job_dir.exists()


def test_cancel_before_destination_selection_cleans_snapshot(app):
    job = job_module().ConversionJob()
    ready, finished = [], []
    job.ready.connect(ready.append)
    job.finished.connect(lambda: finished.append(True))
    job.start(source_bytes())
    wait_until(app, lambda: ready)
    job_dir = job.job_dir
    job.cancel()
    wait_until(app, lambda: finished)
    assert not job_dir.exists()


@pytest.mark.parametrize('exit_code,content', [(2, b'corrupt'), (0, b'corrupt')])
def test_broken_worker_cannot_replace_destination(app, tmp_path, monkeypatch, exit_code, content):
    import sys
    module = job_module()
    script = tmp_path / 'bad_worker.py'
    script.write_text('''import json, sys, time
from pathlib import Path
root=Path(sys.argv[1])
(root/'ready.json').write_text(json.dumps({'page_count':1,'text_pages':1,'image_only_pages':[]}))
while not (root/'command.json').exists(): time.sleep(.02)
command=json.loads((root/'command.json').read_text())
Path(command['staged_path']).write_bytes(b'corrupt')
(root/'result.json').write_text(json.dumps({'type':'complete'}))
sys.exit(''' + str(exit_code) + ')')
    monkeypatch.setattr(module, 'worker_command', lambda job_dir: (sys.executable, [str(script), str(job_dir)]))
    job = module.ConversionJob()
    ready, finished, errors = [], [], []
    job.ready.connect(ready.append)
    job.finished.connect(lambda: finished.append(True))
    job.failed.connect(errors.append)
    dest = tmp_path / 'existing.docx'
    dest.write_bytes(b'untouched')
    job.start(source_bytes())
    wait_until(app, lambda: ready)
    job.proceed(dest)
    wait_until(app, lambda: finished)
    assert len(errors) == 1 and len(finished) == 1
    assert dest.read_bytes() == b'untouched'
    assert not list(tmp_path.glob('.paperedit-word-*'))


def test_cancel_wins_before_completed_process_is_dispatched(app, tmp_path):
    import time
    job = job_module().ConversionJob()
    ready, success, finished = [], [], []
    job.ready.connect(ready.append)
    job.succeeded.connect(success.append)
    job.finished.connect(lambda: finished.append(True))
    dest = tmp_path / 'race.docx'
    dest.write_bytes(b'original')
    job.start(source_bytes())
    wait_until(app, lambda: ready)
    job.proceed(dest)
    job.process.waitForBytesWritten(1000)
    # Intentionally withhold event dispatch while the actual worker completes.
    time.sleep(3)
    job.cancel()
    wait_until(app, lambda: finished)
    assert not success
    assert dest.read_bytes() == b'original'


def test_stale_job_cleanup_preserves_active_job(app, tmp_path):
    from PySide6.QtCore import QLockFile
    module = job_module()
    stale = tmp_path / 'job-stale'
    active = tmp_path / 'job-active'
    stale.mkdir()
    active.mkdir()
    (stale / 'input.pdf').write_bytes(b'private')
    lock = QLockFile(str(active / 'active.lock'))
    assert lock.tryLock(0)
    module.cleanup_stale_jobs(tmp_path)
    assert not stale.exists()
    assert active.exists()
    lock.unlock()


def test_worker_handles_missing_console_streams(tmp_path):
    import subprocess
    import sys
    root = tmp_path / 'private'
    root.mkdir()
    (root / 'input.pdf').write_bytes(source_bytes())
    destination = tmp_path / 'no-console.docx'
    (root / 'command.json').write_text(__import__('json').dumps({'type':'convert', 'staged_path':str(destination)}))
    code = 'import sys; from pathlib import Path; from pdf_editor.conversion_worker import worker_main; sys.stdout=sys.stdin=sys.stderr=None; sys.exit(worker_main(Path(sys.argv[1])))'
    result = subprocess.run([sys.executable, '-c', code, str(root)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert destination.exists()
    assert (root / 'ready.json').exists()
    assert __import__('json').loads((root / 'result.json').read_text())['type'] == 'complete'


def test_missing_output_folder_can_cancel_without_snapshot_leak(app, tmp_path):
    from pdf_editor.conversion import ConversionError
    job = job_module().ConversionJob()
    ready, finished = [], []
    job.ready.connect(ready.append)
    job.finished.connect(lambda: finished.append(True))
    job.start(source_bytes())
    wait_until(app, lambda: ready)
    job_dir = job.job_dir
    with pytest.raises(ConversionError):
        job.proceed(tmp_path / 'missing' / 'out.docx')
    job.cancel()
    wait_until(app, lambda: finished)
    assert not job_dir.exists()
