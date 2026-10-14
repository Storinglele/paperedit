"""Qt controller for a private, cancellable conversion subprocess."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal, QLockFile, QTimer, QStandardPaths

from .conversion import ConversionError, publish_docx
from .conversion_worker import write_message


def job_root():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    return Path(base) / 'paperedit-word-jobs'


def worker_command(job_dir):
    if getattr(sys, 'frozen', False):
        return sys.executable, ['--paperedit-convert-worker', str(job_dir)]
    return sys.executable, [str(Path(__file__).resolve().parents[1] / 'launch.py'),
                           '--paperedit-convert-worker', str(job_dir)]


def cleanup_stale_jobs(root=None):
    root = Path(root) if root is not None else job_root()
    if not root.exists():
        return
    for path in root.glob('job-*'):
        if path.is_symlink() or not path.is_dir():
            continue
        lock = QLockFile(str(path / 'active.lock'))
        if lock.tryLock(0):
            lock.unlock()
            # Remove only the exact staged path recorded for this abandoned job.
            try:
                marker = json.loads((path / 'output.json').read_text(encoding='utf-8'))
                staged = Path(marker['staged_path'])
                if staged.name == '.paperedit-word-' + path.name + '.docx':
                    staged.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError):
                pass
            shutil.rmtree(path, ignore_errors=True)


class ConversionJob(QObject):
    ready = Signal(object)
    succeeded = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setStandardOutputFile(os.devnull)
        self.process.setStandardErrorFile(os.devnull)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._check_ready)
        self.running = False
        self.cancelled = False
        self.job_dir = None
        self.destination = None
        self.staged_path = None
        self._ready = False
        self._error = None
        self._lock = None

    def start(self, data: bytes):
        if self.running:
            raise ConversionError('已有 Word 转换任务正在执行。')
        self.cancelled = False
        self.destination = self.staged_path = None
        self._ready = False
        self._error = None
        try:
            root = job_root()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            cleanup_stale_jobs(root)
            self.job_dir = Path(tempfile.mkdtemp(prefix='job-', dir=root))
            os.chmod(self.job_dir, 0o700)
            self._lock = QLockFile(str(self.job_dir / 'active.lock'))
            if not self._lock.tryLock(0):
                raise ConversionError('无法创建转换任务。')
            snapshot = self.job_dir / 'input.pdf'
            with snapshot.open('xb') as stream:
                os.chmod(snapshot, 0o600)
                stream.write(data)
            program, args = worker_command(self.job_dir)
            self.running = True
            self.process.start(program, args)
            self.timer.start()
        except Exception as exc:
            self._cleanup()
            raise ConversionError('无法创建 Word 转换任务，请检查临时目录空间与权限。') from exc

    def proceed(self, destination: Path):
        if not self.running or not self._ready:
            raise ConversionError('转换任务尚未准备好。')
        if self.destination is not None:
            raise ConversionError('转换任务已经提交。')
        destination = Path(destination).expanduser().absolute()
        if destination.suffix.lower() != '.docx':
            raise ConversionError('请使用 .docx 文件扩展名。')
        try:
            staged = destination.parent / ('.paperedit-word-' + self.job_dir.name + '.docx')
            with staged.open('xb') as stream:
                os.chmod(staged, 0o600)
            self.destination = destination
            self.staged_path = staged
            payload = {'type': 'convert', 'staged_path': str(staged)}
            write_message(self.job_dir / 'output.json', payload)
            write_message(self.job_dir / 'command.json', payload)
        except OSError as exc:
            raise ConversionError('无法写入 Word 文件，请检查保存目录和文件权限。') from exc

    def cancel(self):
        if not self.running:
            return
        # Set before kill; a queued success cannot win over cancellation.
        self.cancelled = True
        self.process.kill()
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._finish()

    def _check_ready(self):
        if not self.running or self.cancelled or self._ready:
            return
        path = self.job_dir / 'ready.json'
        if path.exists():
            try:
                info = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(info['page_count'], int) or not isinstance(info['image_only_pages'], list):
                    raise ValueError('invalid preflight result')
                self._ready = True
                self.ready.emit(info)
            except (OSError, ValueError, KeyError):
                self._abort('转换任务返回了无效结果。')

    def _process_finished(self, exit_code, exit_status):
        if not self.running:
            return
        message = None
        if not self.cancelled:
            try:
                result = json.loads((self.job_dir / 'result.json').read_text(encoding='utf-8'))
                if self._error:
                    message = self._error
                elif exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                    message = result.get('message', '转换失败，原文件未改动。')
                elif result.get('type') != 'complete' or not self.destination or not self.staged_path:
                    message = '转换失败，原文件未改动。'
                else:
                    publish_docx(self.staged_path, self.destination)
            except ConversionError as exc:
                message = str(exc)
            except (OSError, ValueError, KeyError):
                message = self._error or '转换失败，原文件未改动。'
        destination = self.destination
        succeeded = not self.cancelled and message is None
        self._finish()
        if succeeded:
            self.succeeded.emit(str(destination))
        elif message:
            self.failed.emit(message)

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.running:
            self._finish()
            self.failed.emit('无法启动 Word 转换任务。')

    def _abort(self, message):
        self._error = message
        self.process.kill()

    def _cleanup(self):
        self.timer.stop()
        if self.staged_path:
            try:
                self.staged_path.unlink(missing_ok=True)
            except OSError:
                pass
        if self._lock:
            self._lock.unlock()
        if self.job_dir:
            shutil.rmtree(self.job_dir, ignore_errors=True)

    def _finish(self):
        if not self.running:
            return
        self.running = False
        self._cleanup()
        self.finished.emit()
