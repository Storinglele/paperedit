import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from .window import EditorWindow


def main():
    if '--paperedit-convert-worker' in sys.argv:
        from .conversion_worker import worker_main
        index = sys.argv.index('--paperedit-convert-worker')
        return worker_main(Path(sys.argv[index + 1]))
    app = QApplication(sys.argv)
    app.setApplicationName('PaperEdit')
    app.setOrganizationName('PaperEdit')
    window = EditorWindow()
    window.show()
    paths = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
    if paths:
        QTimer.singleShot(0, lambda: window.load_file(Path(paths[0])))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
