"""Export only build inputs; never include PDFs, local runtimes or credentials."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = ('launch.py', 'requirements.txt', 'requirements-dev.txt', 'README.md', 'build_windows.cmd')
FOLDERS = ('pdf_editor', 'scripts', 'tests', '.github/workflows')
SUFFIXES = {'.py', '.ps1', '.sh', '.yml', '.yaml'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/PaperEdit2-Windows-build-source.zip')
    args = parser.parse_args()
    source = args.source_root.resolve()
    files = [source/name for name in TOP_FILES]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        parser.error('Missing build inputs: ' + ', '.join(missing))
    for folder in FOLDERS:
        files.extend(path for path in sorted((source/folder).rglob('*'))
                     if path.is_file() and not path.is_symlink()
                     and path.suffix in SUFFIXES and '__pycache__' not in path.parts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'PaperEdit2-source/' + path.relative_to(source).as_posix())
    print(args.output)


if __name__ == '__main__':
    main()
