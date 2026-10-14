"""Check the distributed source archive, including its privacy boundary."""
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def test_source_archive_contains_build_inputs_and_excludes_private_artifacts(tmp_path):
    source = tmp_path / '中文源码'
    source.mkdir()
    for filename in ('launch.py', 'requirements.txt', 'requirements-dev.txt', 'README.md', 'build_windows.cmd'):
        (source / filename).write_text('public input', encoding='utf-8')
    for folder, name in [('pdf_editor', 'window.py'), ('scripts', 'build_windows.ps1'),
                         ('tests', 'test_document.py'), ('.github/workflows', 'build-windows.yml'),
                         ('artifacts', 'private.pdf'), ('.venv', 'python.exe'),
                         ('pdf_editor/__pycache__', 'window.pyc')]:
        target = source / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('input', encoding='utf-8')
    out = tmp_path / 'source.zip'
    result = subprocess.run([sys.executable, str(ROOT/'scripts/package_windows_source.py'),
                             '--source-root', str(source), '--output', str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert 'PaperEdit2-source/scripts/build_windows.ps1' in names
        assert 'PaperEdit2-source/.github/workflows/build-windows.yml' in names
        assert 'PaperEdit2-source/pdf_editor/window.py' in names
        assert archive.read('PaperEdit2-source/README.md') == b'public input'
        assert not any('private.pdf' in name or '.venv' in name or '__pycache__' in name for name in names)


def test_source_archive_refuses_incomplete_build_inputs(tmp_path):
    out = tmp_path/'source.zip'
    result = subprocess.run([sys.executable, str(ROOT/'scripts/package_windows_source.py'),
                             '--source-root', str(tmp_path), '--output', str(out)], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Missing build inputs' in result.stderr
    assert not out.exists()
