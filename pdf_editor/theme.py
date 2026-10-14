"""Desktop editor palette: white controls, graphite canvas, teal selection."""
STYLE = '''
QMainWindow { background: #F5F6F8; }
QWidget { font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", "Helvetica Neue"; font-size: 13px; color: #263445; }
QToolBar { background: #FFFFFF; border: 0; border-bottom: 1px solid #DFE5EA; spacing: 6px; padding: 9px; }
QToolButton { border: 0; border-radius: 6px; padding: 8px 11px; }
QToolButton:hover { background: #EAF2F4; }
QToolButton:checked { background: #E5E3FD; color: #7770F2; }
QToolButton:disabled { color: #A7AFBA; }
QPushButton { background: #FFFFFF; border: 1px solid #CDD6DE; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { border-color: #7770F2; background: #F2F1FE; }
QPushButton:disabled { color: #9AA5B2; background: #F0F2F5; }
QPushButton#primary { background: #7770F2; border-color: #7770F2; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #635BD7; }
QPushButton#primary:disabled { background: #B7B3E7; border-color: #B7B3E7; }
QLineEdit, QPlainTextEdit, QDoubleSpinBox, QSpinBox, QComboBox { background: white; border: 1px solid #D4DCE4; border-radius: 5px; padding: 6px; selection-background-color: #7770F2; }
QLineEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color: #7770F2; }
QListWidget { background: #EFF2F5; border: 0; padding: 10px; outline: 0; }
QListWidget::item { border: 2px solid transparent; border-radius: 5px; padding: 8px; margin: 5px 0; }
QListWidget::item:selected { background: #E5E3FD; border-color: #7770F2; }
QScrollArea { border: 0; background: #D9DFE5; }
QStatusBar { background: white; border-top: 1px solid #DFE5EA; color: #536477; padding: 4px; }
QSplitter::handle { background: #DFE5EA; width: 1px; }
QLabel#heading { font-size: 19px; font-weight: 600; }
QLabel#muted { color: #647588; }
QLabel#warning { color: #936224; background: #FFF5E3; padding: 9px; border-radius: 5px; }
QFrame#inspector { background: #FFFFFF; }
'''
