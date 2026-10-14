"""Qt controller for a private, cancellable conversion subprocess."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal

from .conversion import ConversionError, inspect_pdf, publish_docx


JOB_ROOT = Path(tempfile.gettempdir()) / 'paperedit-word-jobs'


def worker_command(job_dir):
    if getattr(sys, 'frozen', False):
        return sys.executable, ['--paperedit-convert-worker', str(job_dir)]
    return sys.executable, ['-m', 'pdf_editor', '--paperedit-convert-worker', str(job_dir)]


def cleanup_stale_jobs(root=JOB_ROOT):
    root = Path(root)
    if not root.exists():
        return
    from PySide6.QtCore import QLockFile
    for path in root.glob('job-*'):
        lock = QLockFile(str(path / 'active.lock'))
        if lock.tryLock(0):
            lock.unlock()
            shutil.rmtree(path, ignore_errors=True)


class ConversionJob(QObject):
    ready = Signal(object)
    succeeded = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._process_finished)
        self.running = False
        self.cancelled = False
        self.completed = False
        self.job_dir = None
        self.destination = None
        self.staged_path = None
        self._buffer = b''
        self._lock = None

    def start(self, data: bytes):
        if self.running:
            raise ConversionError('已有 Word 转换任务正在执行。')
        cleanup_stale_jobs()
        JOB_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.job_dir = Path(tempfile.mkdtemp(prefix='job-', dir=JOB_ROOT))
        os.chmod(self.job_dir, 0o700)
        (self.job_dir / 'input.pdf').write_bytes(data)
        os.chmod(self.job_dir / 'input.pdf', 0o600)
        from PySide6.QtCore import QLockFile
        self._lock = QLockFile(str(self.job_dir / 'active.lock'))
        if not self._lock.tryLock(0):
            raise ConversionError('无法创建转换任务。')
        self.cancelled = False
        self.completed = False
        self.running = True
        self._buffer = b''
        program, args = worker_command(self.job_dir)
        self.process.start(program, args)
        if not self.process.waitForStarted(5000):
            self._fail('无法启动 Word 转换任务。')

    def proceed(self, destination: Path):
        if not self.running or not self.job_dir:
            raise ConversionError('转换任务尚未准备好。')
        if self.destination is not None:
            raise ConversionError('转换任务已经提交。')
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.lower() != '.docx':
            raise ConversionError('请使用 .docx 文件扩展名。')
        if not destination.parent.exists():
            raise ConversionError('保存目录不存在。')
        self.destination = destination
        self.staged_path = destination.parent / f'.paperedit-word-{os.getpid()}-{id(self)}.docx'
        payload = json.dumps({'type': 'convert', 'staged_path': str(self.staged_path)}) + '\n'
        self.process.write(payload.encode())

    def cancel(self):
        if not self.running:
            return
        self.cancelled = True
        self.process.kill()

    def _read_output(self):
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            if not line.strip():
                continue
            try:
                self._message(json.loads(line))
            except Exception:
                self._fail('转换任务返回了无效结果。')

    def _message(self, message):
        if message.get('type') == 'ready':
            self.ready.emit(message)
        elif message.get('type') == 'error':
            self._fail(message.get('message', '转换失败。'))
        elif message.get('type') == 'complete':
            self.completed = True

    def _process_finished(self, exit_code, exit_status):
        self._read_output()
        if self.cancelled:
            self._finish()
            return
        if exit_code != 0 or not self.completed or not self.destination or not self.staged_path:
            self._fail('转换失败，原文件未改动。')
            return
        try:
            publish_docx(self.staged_path, self.destination)
            self.succeeded.emit(str(self.destination))
        except ConversionError as exc:
            self._fail(str(exc))
        self._finish()

    def _fail(self, message):
        if self.running:
            self.failed.emit(message)
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        self._finish()

    def _finish(self):
        if not self.running:
            return
        self.running = False
        if self.staged_path:
            Path(self.staged_path).unlink(missing_ok=True)
        if self._lock:
            self._lock.unlock()
        if self.job_dir:
            shutil.rmtree(self.job_dir, ignore_errors=True)
        self.finished.emit()

