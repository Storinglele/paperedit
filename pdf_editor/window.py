"""PaperEdit desktop window: document navigation and explicit text editing."""
from pathlib import Path
import fitz
from PySide6.QtCore import Qt, QSize, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QPlainTextEdit, QDoubleSpinBox, QSpinBox, QLineEdit,
    QToolBar, QSplitter, QListWidget, QListWidgetItem, QScrollArea, QFrame,
    QFileDialog, QMessageBox, QColorDialog, QInputDialog, QAbstractItemView,
)
from .document import DocumentSession, EditError, PasswordRequired
from .canvas import PageCanvas
from .render import RenderTask, ThumbnailTask
from .theme import STYLE
from .fonts import choose_font
from .conversion import ConversionError, inspect_pdf
from .conversion_job import ConversionJob


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session = None
        self.current_page = 0
        self.mode = 'read'
        self.scale = 1.0
        self.fit_width = True
        self.selected_span = None
        self.pending_add = False
        self.text_color = (0, 0, 0)
        self.search_hits = []
        self.search_index = -1
        self.render_token = 0
        self.thumbnail_token = 0
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._workers = {}
        self._draft_original = None
        self.word_export_job = None
        self.setWindowTitle('PaperEdit · PDF 编辑器')
        self.resize(1320, 880)
        self.setMinimumSize(980, 650)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self._build_toolbar()
        self._build_content()
        self._build_menu()
        self.statusBar().showMessage('打开 PDF 后，选择“编辑文字”开始修改。')
        self._update_actions()

    def _action(self, text, callback, shortcut=None, checkable=False):
        action = QAction(text, self)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        self.toolbar.addAction(action)
        return action

    def _build_toolbar(self):
        self.toolbar = QToolBar('文档工具')
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        self.open_action = self._action('打开 PDF', self.open_dialog, 'Ctrl+O')
        self.save_action = self._action('另存为', self.save_dialog, 'Ctrl+Shift+S')
        self.word_action = self._action('导出 Word', self.export_word_dialog, 'Ctrl+Alt+W')
        self.toolbar.addSeparator()
        self.mode_actions = {}
        group = QActionGroup(self)
        for mode, label in [('read', '阅读'), ('edit', '编辑文字'), ('add', '添加文字')]:
            a = self._action(label, lambda checked=False, m=mode: self.set_mode(m), checkable=True)
            group.addAction(a)
            self.mode_actions[mode] = a
        self.mode_actions['read'].setChecked(True)
        self.toolbar.addSeparator()
        self.undo_action = self._action('撤销', self.undo, 'Ctrl+Z')
        self.redo_action = self._action('重做', self.redo, 'Ctrl+Shift+Z')
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('搜索文档文字')
        self.search_input.setAccessibleName('搜索文档文字')
        self.search_input.setMaximumWidth(190)
        self.search_input.returnPressed.connect(self.search_next)
        self.search_input.textChanged.connect(self._reset_search)
        self.toolbar.addWidget(self.search_input)
        self._action('查找下一个', self.search_next)
        self.zoom_input = QSpinBox()
        self.zoom_input.setRange(25, 300)
        self.zoom_input.setValue(100)
        self.zoom_input.setSuffix('%')
        self.zoom_input.setFixedWidth(88)
        self.zoom_input.setAccessibleName('缩放比例')
        self.zoom_input.valueChanged.connect(self.set_zoom)
        self.toolbar.addWidget(self.zoom_input)
        self._action('适应宽度', self.fit_page_width)
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self.search_input.setFocus)
        QShortcut(QKeySequence('Ctrl+C'), self, activated=self.copy_selected)
        QShortcut(QKeySequence('Ctrl+S'), self, activated=self.save_dialog)

    def _build_content(self):
        splitter = QSplitter()
        self.setCentralWidget(splitter)
        self.thumbnails = QListWidget()
        self.thumbnails.setFixedWidth(164)
        self.thumbnails.setIconSize(QSize(112, 150))
        self.thumbnails.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnails.setFlow(QListWidget.Flow.TopToBottom)
        self.thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thumbnails.setAccessibleName('页面缩略图')
        self.thumbnails.currentRowChanged.connect(self.go_to_page)
        splitter.addWidget(self.thumbnails)
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        navigation.setContentsMargins(16, 10, 16, 10)
        prev = QPushButton('上一页')
        prev.clicked.connect(lambda: self.go_to_page(self.current_page - 1))
        next_btn = QPushButton('下一页')
        next_btn.clicked.connect(lambda: self.go_to_page(self.current_page + 1))
        self.page_input = QSpinBox()
        self.page_input.setRange(1, 1)
        self.page_input.setAccessibleName('当前页码')
        self.page_input.valueChanged.connect(lambda n: self.go_to_page(n - 1))
        self.page_count_label = QLabel('/ 0 页')
        self.document_label = QLabel('PaperEdit')
        self.document_label.setObjectName('muted')
        navigation.addWidget(prev)
        navigation.addWidget(self.page_input)
        navigation.addWidget(self.page_count_label)
        navigation.addWidget(next_btn)
        navigation.addStretch()
        navigation.addWidget(self.document_label)
        layout.addLayout(navigation)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.page_holder = QWidget()
        self.page_holder.setStyleSheet('background: #D9DFE5;')
        self.page_layout = QVBoxLayout(self.page_holder)
        self.page_layout.setContentsMargins(26, 24, 26, 24)
        self.page_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = PageCanvas()
        self.canvas.hide()
        self.canvas.span_selected.connect(self.select_span)
        self.canvas.add_requested.connect(self.add_at)
        self.canvas.inline_changed.connect(self._inline_text_changed)
        self.canvas.commit_requested.connect(self.apply_edit)
        self.canvas.cancel_requested.connect(self.cancel_edit)
        self.canvas.rect_changed.connect(self._canvas_rect_changed)
        self.page_layout.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignCenter)
        self.welcome = QLabel('打开一个 PDF\n\n修改原有文字，或在页面上添加文字。\n文件在本地处理。')
        self.welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome.setStyleSheet('font-size: 19px; color: #52677B; padding: 90px 30px; background: transparent;')
        self.page_layout.addWidget(self.welcome)
        self.scroll.setWidget(self.page_holder)
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)
        splitter.addWidget(center)
        self.inspector = QFrame()
        self.inspector.setObjectName('inspector')
        self.inspector.setFixedWidth(290)
        side = QVBoxLayout(self.inspector)
        side.setContentsMargins(20, 24, 20, 20)
        side.setSpacing(14)
        title = QLabel('文字属性')
        title.setObjectName('heading')
        side.addWidget(title)
        self.help_label = QLabel('选择“编辑文字”，再点击页面上要修改的文字。')
        self.help_label.setWordWrap(True)
        self.help_label.setObjectName('muted')
        side.addWidget(self.help_label)
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText('选中文字后在这里修改')
        self.text_input.setAccessibleName('文字内容')
        self.text_input.setMinimumHeight(150)
        self.text_input.setMaximumHeight(230)
        side.addWidget(self.text_input)
        self.text_input.textChanged.connect(self._property_text_changed)
        form = QFormLayout()
        form.setSpacing(10)
        self.size_input = self._spin(1, 200, 14)
        self.color_button = QPushButton('选择文字颜色')
        self.color_button.clicked.connect(self.pick_color)
        self.font_label = QLabel('按原字体优先，中文自动选择可用字体')
        self.font_label.setWordWrap(True)
        self.font_label.setObjectName('muted')
        self.x_input = self._spin(0, 100000, 60)
        self.y_input = self._spin(0, 100000, 80)
        self.width_input = self._spin(1, 100000, 250)
        self.height_input = self._spin(1, 100000, 50)
        for label, control in [('字号', self.size_input), ('颜色', self.color_button), ('X 位置', self.x_input), ('Y 位置', self.y_input), ('宽度', self.width_input), ('高度', self.height_input)]:
            control.setAccessibleName(label)
            form.addRow(label, control)
        side.addLayout(form)
        side.addWidget(self.font_label)
        self.apply_button = QPushButton('应用修改')
        self.apply_button.setObjectName('primary')
        self.apply_button.clicked.connect(self.apply_edit)
        side.addWidget(self.apply_button)
        self.autosize_button = QPushButton('自适应文字框')
        self.autosize_button.clicked.connect(self.autosize_text)
        side.addWidget(self.autosize_button)
        copy = QPushButton('复制选中文字')
        copy.clicked.connect(self.copy_selected)
        side.addWidget(copy)
        self.warning_label = QLabel('')
        self.warning_label.setObjectName('warning')
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        side.addWidget(self.warning_label)
        side.addStretch()
        note = QLabel('位置和大小以 PDF 点为单位。\n扫描图片中的原文字需要 OCR。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        side.addWidget(note)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(1, 1)
        self.property_controls = [self.text_input, self.size_input, self.color_button, self.x_input, self.y_input, self.width_input, self.height_input]
        for spin in [self.x_input, self.y_input, self.width_input, self.height_input]:
            spin.valueChanged.connect(self.preview_rect)
        self.size_input.valueChanged.connect(self.preview_rect)

    @staticmethod
    def _spin(minimum, maximum, value):
        s = QDoubleSpinBox()
        s.setRange(minimum, maximum)
        s.setValue(value)
        s.setDecimals(1)
        s.setSuffix(' pt')
        return s

    def _build_menu(self):
        file_menu = self.menuBar().addMenu('文件')
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.word_action)
        edit_menu = self.menuBar().addMenu('编辑')
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        copy = edit_menu.addAction('复制选中文字')
        copy.triggered.connect(self.copy_selected)
        sample_action = file_menu.addAction('打开编辑示例')
        sample_action.triggered.connect(self.open_example)
        help_menu = self.menuBar().addMenu('帮助')
        about = help_menu.addAction('关于 PaperEdit')
        about.triggered.connect(lambda: QMessageBox.information(self, 'PaperEdit', 'PaperEdit 0.1\n本地 PDF 文字编辑器\n\n支持水平文字编辑和添加文字。\n复杂排版、竖排、OCR 不在第一版范围内。'))

    def open_example(self):
        import sys
        if getattr(sys, 'frozen', False):
            path = Path(sys._MEIPASS) / 'examples' / '编辑示例.pdf'
        else:
            path = Path(__file__).resolve().parents[1] / 'artifacts' / '编辑示例.pdf'
        self.load_file(path)

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开 PDF', '', 'PDF 文件 (*.pdf)')
        if path:
            self.load_file(path)

    def _confirm_discard(self):
        if not self.flush_pending_edit():
            return False
        if not self.session or not self.session.dirty:
            return True
        choice = QMessageBox.question(self, '保存修改', '当前 PDF 有未保存的修改。',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self.save_dialog()
        return True

    def load_file(self, path):
        if not self._confirm_discard():
            return
        password = ''
        while True:
            try:
                session = DocumentSession.open(path, password)
                break
            except PasswordRequired:
                password, ok = QInputDialog.getText(self, 'PDF 密码', '请输入打开密码：', QLineEdit.EchoMode.Password)
                if not ok:
                    return
            except EditError as exc:
                self.show_error(str(exc))
                return
        self.session = session
        self.current_page = 0
        self.selected_span = None
        self.pending_add = False
        self.fit_width = True
        self._reset_search()
        self.page_count_label.setText(f'/ {session.page_count} 页')
        self.page_input.blockSignals(True)
        self.page_input.setRange(1, session.page_count)
        self.page_input.setValue(1)
        self.page_input.blockSignals(False)
        self.document_label.setText(Path(path).name)
        self.thumbnails.blockSignals(True)
        self.thumbnails.clear()
        for n in range(session.page_count):
            item = QListWidgetItem(f'第 {n + 1} 页')
            item.setSizeHint(QSize(132, 185))
            self.thumbnails.addItem(item)
        self.thumbnails.setCurrentRow(0)
        self.thumbnails.blockSignals(False)
        self.set_mode('read')
        self.welcome.hide()
        self.canvas.show()
        self.render_page()
        self.render_thumbnails()
        self._update_actions()
        self.setWindowTitle(f'{Path(path).name} — PaperEdit')

    def set_mode(self, mode):
        if not self.flush_pending_edit():
            self.mode_actions[self.mode].setChecked(True)
            return
        self.canvas.hide_editor()
        self._draft_original = None
        self.mode = mode
        self.canvas.mode = mode
        self.mode_actions[mode].setChecked(True)
        self.selected_span = None
        self.pending_add = False
        self.canvas.selected = None
        self.canvas.update()
        self.text_input.clear()
        self.help_label.setText({'read': '点击原有文字直接编辑；选中后也可复制。',
                                'edit': '点击文字直接输入，点击“完成编辑”或按 Ctrl+Enter（Mac：⌘Enter）。',
                                'add': '点击页面上的位置，输入文字后点击“添加到页面”。'}[mode])
        self.apply_button.setText('添加到页面' if mode == 'add' else '应用修改')
        self.warning_label.hide()
        self._update_actions()

    def select_span(self, span):
        if not self.flush_pending_edit():
            return
        if span.revision != self.session.revision:
            current = next((s for s in self.session.spans(self.current_page) if s.text == span.text and s.bbox == span.bbox), None)
            if not current:
                return
            span = current
        if self.mode == 'read' and span.editable and self.session.editable:
            self.set_mode('edit')
        self.selected_span = span
        self.pending_add = False
        self.canvas.selected = span
        self.text_input.setPlainText(span.text)
        for control, value in [(self.size_input, span.size), (self.x_input, span.bbox[0]), (self.y_input, span.bbox[1]), (self.width_input, span.bbox[2] - span.bbox[0] + 3), (self.height_input, max(span.bbox[3] - span.bbox[1] + 3, span.size * 1.5))]:
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.text_color = span.color
        self._update_color()
        self.font_label.setText(f'原字体：{span.font}\n缺少新字符时使用替代字体。')
        self.warning_label.setVisible(not span.editable)
        self.warning_label.setText(span.reason)
        self.canvas.update()
        self._update_actions()
        self._draft_original = self._draft_values()
        if self.mode == 'edit' and span.editable and self.session.editable:
            self._show_inline_editor()

    def add_at(self, x, y):
        if not self.flush_pending_edit():
            return
        if not self.session or not self.session.editable:
            return
        info = self.session.page_info(self.current_page)
        self.selected_span = None
        self.pending_add = True
        self.text_input.clear()
        for control, value in [(self.x_input, x), (self.y_input, y),
                               (self.width_input, max(1, min(250, info['pdf_width'] - x))),
                               (self.height_input, max(1, min(70, info['pdf_height'] - y)))]:
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.font_label.setText('Helvetica；中文自动选择可用字体。')
        self.warning_label.hide()
        self._update_actions()
        self.preview_rect()
        self._draft_original = self._draft_values()
        self._show_inline_editor()

    def edit_rect(self):
        x, y = self.x_input.value(), self.y_input.value()
        return (x, y, x + self.width_input.value(), y + self.height_input.value())

    def preview_rect(self):
        if self.pending_add or self.selected_span and self.mode == 'edit':
            self.canvas.selected = self.edit_rect()
            self.canvas.update()
            if self.canvas.inline_editor.isVisible():
                self.canvas.position_editor(self.edit_rect())
                font = self.canvas.inline_editor.font()
                font.setPixelSize(max(6, round(self.size_input.value() * self.scale)))
                self.canvas.inline_editor.setFont(font)

    def _draft_values(self):
        return (self.text_input.toPlainText(), self.size_input.value(), self.text_color, self.edit_rect())

    def has_pending_edit(self):
        if not self.session or not (self.selected_span and self.mode == 'edit' or self.pending_add):
            return False
        if self.pending_add:
            return bool(self.text_input.toPlainText().strip())
        return self._draft_original is not None and self._draft_values() != self._draft_original

    def flush_pending_edit(self):
        if self.has_pending_edit():
            return self.apply_edit()
        return True

    def _inline_text_changed(self, text):
        self.text_input.blockSignals(True)
        self.text_input.setPlainText(text)
        self.text_input.blockSignals(False)
        self._grow_inline_width(text)
        self.statusBar().showMessage('正在编辑；点击“完成编辑”或按 Ctrl+Enter（Mac：⌘Enter）。保存时会自动应用。')

    def _grow_inline_width(self, text):
        if not self.session or not text or '\n' in text:
            return
        try:
            with fitz.open(stream=self.session.snapshot(), filetype='pdf') as doc:
                font = choose_font(doc, doc[self.current_page], self.selected_span.font if self.selected_span else None, text).font
            needed = font.text_length(text, fontsize=self.size_input.value()) + 3
            if needed <= self.width_input.value():
                return
            x, y = self.x_input.value(), self.y_input.value()
            available = self.session.page_info(self.current_page)['pdf_width'] - x
            for other in self.session.spans(self.current_page):
                if self.selected_span and other.key == self.selected_span.key:
                    continue
                if other.bbox[0] > x and other.bbox[1] < y + self.height_input.value() and other.bbox[3] > y:
                    available = min(available, other.bbox[0] - x - 2)
            self.width_input.setValue(max(self.width_input.value(), min(needed, available)))
        except ValueError:
            pass  # The transactional engine surfaces unsupported characters on commit.

    def _property_text_changed(self):
        if self.canvas.inline_editor.isVisible():
            self.canvas.inline_editor.blockSignals(True)
            self.canvas.inline_editor.setPlainText(self.text_input.toPlainText())
            self.canvas.inline_editor.blockSignals(False)

    def _canvas_rect_changed(self, box):
        for control, value in [(self.x_input, box[0]), (self.y_input, box[1]), (self.width_input, box[2] - box[0]), (self.height_input, box[3] - box[1])]:
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.preview_rect()

    def _show_inline_editor(self):
        try:
            with fitz.open(stream=self.session.snapshot(), filetype='pdf') as doc:
                choice = choose_font(doc, doc[self.current_page], self.selected_span.font if self.selected_span else None, self.text_input.toPlainText())
            self.canvas.show_editor(self.text_input.toPlainText(), self.edit_rect(), self.size_input.value(), self.text_color, choice.buffer)
        except ValueError as exc:
            self.show_error(str(exc))

    def cancel_edit(self):
        self.canvas.hide_editor()
        self.canvas.selected = None
        self.selected_span = None
        self.pending_add = False
        self._draft_original = None
        self.text_input.clear()
        self._update_actions()
        self.canvas.update()
        self.statusBar().showMessage('已取消本次编辑。')

    def autosize_text(self):
        if not self.session or not (self.selected_span or self.pending_add):
            return
        with fitz.open(stream=self.session.snapshot(), filetype='pdf') as doc:
            choice = choose_font(doc, doc[self.current_page], self.selected_span.font if self.selected_span else None, self.text_input.toPlainText())
        text = self.text_input.toPlainText()
        size = self.size_input.value()
        x, y = self.x_input.value(), self.y_input.value()
        paragraphs = text.split('\n')
        desired = max([choice.font.text_length(t, fontsize=size) for t in paragraphs] or [1]) + 3
        info = self.session.page_info(self.current_page)
        available = info['pdf_width'] - x
        for span in self.session.spans(self.current_page):
            if self.selected_span and span.key == self.selected_span.key:
                continue
            if span.bbox[0] > x and span.bbox[1] < y + size * 1.5 and span.bbox[3] > y:
                available = min(available, span.bbox[0] - x - 2)
        width = max(1, min(desired, available))
        lines = sum(max(1, int(choice.font.text_length(t, fontsize=size) // width) + 1) for t in paragraphs)
        height = max(size * 1.5 * lines, (choice.font.ascender - choice.font.descender) * size + 3)
        self.width_input.setValue(width)
        self.height_input.setValue(min(height, info['pdf_height'] - y))
        self.preview_rect()

    def pick_color(self):
        color = QColorDialog.getColor(QColor.fromRgbF(*self.text_color), self, '文字颜色')
        if color.isValid():
            self.text_color = (color.redF(), color.greenF(), color.blueF())
            self._update_color()
            if self.canvas.inline_editor.isVisible():
                self._show_inline_editor()

    def _update_color(self):
        color = QColor.fromRgbF(*self.text_color)
        self.color_button.setText(f'颜色 {color.name()}')
        self.color_button.setStyleSheet(f'border-left: 8px solid {color.name()};')

    def apply_edit(self):
        if not self.session:
            return False
        try:
            args = (self.current_page, self.text_input.toPlainText(), self.size_input.value(), self.text_color, self.edit_rect())
            if self.pending_add:
                self.session.add_text(*args)
            elif self.selected_span and self.mode == 'edit':
                self.session.replace(args[0], self.selected_span, *args[1:])
            else:
                return True
        except EditError as exc:
            self.show_error(str(exc))
            return False
        note = self.session.last_font_note
        self._draft_original = None
        self.canvas.hide_editor()
        self.selected_span = None
        self.pending_add = False
        self.warning_label.hide()
        self._reset_search()
        self.render_page()
        self.render_thumbnails([self.current_page])
        self._update_actions()
        self.statusBar().showMessage(f'修改已应用。{note}；请另存为 PDF。')
        return True

    def undo(self):
        if self.session:
            self.session.undo()
            self._after_history()

    def redo(self):
        if self.session:
            self.session.redo()
            self._after_history()

    def _after_history(self):
        self._draft_original = None
        self.canvas.hide_editor()
        self.selected_span = None
        self.pending_add = False
        self._reset_search()
        self.render_page()
        self.render_thumbnails([self.current_page])
        self._update_actions()

    def save_dialog(self):
        if not self.flush_pending_edit():
            return False
        if not self.session:
            return False
        source = self.session.source
        suggested = source.with_name(source.stem + '-已编辑.pdf') if source else Path.home() / '已编辑.pdf'
        path, _ = QFileDialog.getSaveFileName(self, '另存 PDF', str(suggested), 'PDF 文件 (*.pdf)')
        if not path:
            return False
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        try:
            self.session.save_as(path)
        except EditError as exc:
            self.show_error(str(exc))
            return False
        self._update_actions()
        self.statusBar().showMessage(f'已保存：{path}')
        return True

    def export_word_dialog(self):
        if self.word_export_job and self.word_export_job.running:
            self.statusBar().showMessage('正在转换为 Word，请等待当前任务完成。')
            return False
        if not self.flush_pending_edit() or not self.session:
            return False
        if not self.session.can_extract:
            self.show_error('此 PDF 的权限不允许提取文字，无法导出 Word。')
            return False
        try:
            info = inspect_pdf(self.session.snapshot())
        except ConversionError as exc:
            self.show_error(str(exc))
            return False
        if info.image_only_pages:
            pages = '、'.join(str(n) for n in info.image_only_pages)
            choice = QMessageBox.question(self, '扫描页面提示',
                f'第 {pages} 页没有可提取文字，图片中的文字无法编辑。继续导出吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if choice != QMessageBox.StandardButton.Yes:
                return False
        source = self.session.source
        suggested = source.with_suffix('.docx') if source else Path.home() / '导出.docx'
        path, _ = QFileDialog.getSaveFileName(self, '导出 Word', str(suggested), 'Word 文档 (*.docx)')
        if not path:
            return False
        if not path.lower().endswith('.docx'):
            path += '.docx'
        self._start_word_export(Path(path), info)
        return True

    def _start_word_export(self, destination, info=None):
        if self.word_export_job and self.word_export_job.running:
            return False
        if not self.flush_pending_edit():
            return False
        job = ConversionJob(self)
        self.word_export_job = job
        job.ready.connect(lambda details: self._word_ready(details, destination))
        job.succeeded.connect(self._word_succeeded)
        job.failed.connect(self._word_failed)
        job.finished.connect(self._word_finished)
        try:
            job.start(self.session.snapshot())
        except ConversionError as exc:
            self.word_export_job = None
            self.show_error(str(exc))
            return False
        self.word_action.setEnabled(False)
        self.statusBar().showMessage('正在转换为 Word…')
        return True

    def _word_ready(self, details, destination):
        if details.get('image_only_pages'):
            self.statusBar().showMessage('正在转换为 Word；图片页中的原文字无法编辑。')
        try:
            self.word_export_job.proceed(destination)
        except ConversionError as exc:
            self._word_failed(str(exc))

    def _word_succeeded(self, path):
        self.statusBar().showMessage(f'Word 已导出：{path}')
        QMessageBox.information(self, '导出完成', f'已生成可编辑 Word 文件：\n{path}')

    def _word_failed(self, message):
        self.show_error(message)

    def _word_finished(self):
        job = self.word_export_job
        self.word_action.setEnabled(bool(self.session))
        if job and job.cancelled:
            self.statusBar().showMessage('已取消 Word 导出。')
        self.word_export_job = None
        self._update_actions()

    def go_to_page(self, number):
        if not self.session or number < 0 or number >= self.session.page_count or number == self.current_page:
            return
        if not self.flush_pending_edit():
            self.page_input.blockSignals(True)
            self.page_input.setValue(self.current_page + 1)
            self.page_input.blockSignals(False)
            return
        self.canvas.hide_editor()
        self._draft_original = None
        self.current_page = number
        self.selected_span = None
        self.pending_add = False
        self.page_input.blockSignals(True)
        self.page_input.setValue(number + 1)
        self.page_input.blockSignals(False)
        self.thumbnails.blockSignals(True)
        self.thumbnails.setCurrentRow(number)
        self.thumbnails.blockSignals(False)
        self.render_page()
        self._update_actions()

    def render_page(self):
        if not self.session:
            return
        self.render_token += 1
        info = self.session.page_info(self.current_page)
        if self.fit_width:
            self.scale = max(.25, min(3, (self.scroll.viewport().width() - 60) / info['width']))
        # Bound allocations even on PDFs with unusually large page sizes.
        self.scale = min(self.scale, 6000 / max(info['width'], info['height']))
        self.zoom_input.blockSignals(True)
        self.zoom_input.setValue(round(self.scale * 100))
        self.zoom_input.blockSignals(False)
        self.canvas.configure_geometry(info['pdf_width'], info['pdf_height'], info['rotation'], self.scale)
        self.canvas.clear_page()
        self.page_holder.adjustSize()
        task = RenderTask(self.session.snapshot(), self.current_page, min(self.scale * self.devicePixelRatioF(), 6000 / max(info['width'], info['height'])), self.session.revision, self.render_token)
        task.signals.ready.connect(self._page_ready)
        task.signals.error.connect(self._render_error)
        self._workers[('page', self.render_token)] = task
        self.pool.start(task)
        self.statusBar().showMessage(f'正在渲染第 {self.current_page + 1} 页…')

    def _page_ready(self, token, image, spans):
        self._workers.pop(('page', token), None)
        if token != self.render_token or not self.session:
            return
        self.canvas.set_page(image, spans)
        if self.pending_add or self.selected_span and self.mode == 'edit':
            self._show_inline_editor()
        if not spans:
            self.warning_label.setText('本页没有可提取文字。可添加文字，图片中的原文字需要 OCR。')
            self.warning_label.show()
        elif not self.session.editable:
            self.warning_label.setText('此 PDF 的权限不允许修改，可阅读和复制文字。')
            self.warning_label.show()
        else:
            self.warning_label.hide()
        self.statusBar().showMessage(f'第 {self.current_page + 1} 页 · {len(spans)} 个文字片段 · {"有未保存修改" if self.session.dirty else "本地 PDF"}')

    def _render_error(self, token, message):
        self._workers.pop(('page', token), None)
        if token == self.render_token:
            self.show_error(f'页面渲染失败：{message}')

    def render_thumbnails(self, pages=None):
        if pages is None:
            self.thumbnail_token += 1
        task = ThumbnailTask(self.session.snapshot(), self.thumbnail_token, pages)
        task.signals.ready.connect(self._thumbnail_ready)
        task.signals.error.connect(lambda token, msg: self.statusBar().showMessage('部分缩略图生成失败：' + msg))
        self.pool.start(task)

    def _thumbnail_ready(self, token, number, image):
        if token == self.thumbnail_token and number < self.thumbnails.count():
            self.thumbnails.item(number).setIcon(QIcon(QPixmap.fromImage(image)))

    def set_zoom(self, percent):
        if self.session:
            self.fit_width = False
            self.scale = percent / 100
            self.render_page()

    def fit_page_width(self):
        self.fit_width = True
        self.render_page()

    def _reset_search(self, *args):
        self.search_hits = []
        self.search_index = -1
        self.canvas.search_rects = []
        self.canvas.update()

    def search_next(self):
        if not self.session or not self.search_input.text().strip():
            return
        if not self.search_hits:
            self.search_hits = self.session.search(self.search_input.text())
        if not self.search_hits:
            self.statusBar().showMessage('没有找到匹配文字。扫描图片中的文字无法直接搜索。')
            return
        self.search_index = (self.search_index + 1) % len(self.search_hits)
        page, rect = self.search_hits[self.search_index]
        self.go_to_page(page)
        self.canvas.search_rects = [rect]
        self.canvas.update()
        self.statusBar().showMessage(f'匹配 {self.search_index + 1}/{len(self.search_hits)} · 第 {page + 1} 页')
        display = self.canvas.display_rect(rect)
        self.scroll.ensureVisible(round(display.center().x()) + 26, round(display.center().y()) + 24, 50, 50)

    def copy_selected(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QPlainTextEdit, QLineEdit)) and focus.hasFocus():
            if isinstance(focus, QPlainTextEdit) and focus.textCursor().hasSelection():
                focus.copy()
                return
            if isinstance(focus, QLineEdit) and focus.hasSelectedText():
                focus.copy()
                return
        if self.selected_span:
            QApplication.clipboard().setText(self.selected_span.text)
            self.statusBar().showMessage('已复制选中文字。')

    def _update_actions(self):
        loaded = self.session is not None
        editable = loaded and self.session.editable
        self.save_action.setEnabled(loaded)
        self.word_action.setEnabled(loaded and not (self.word_export_job and self.word_export_job.running))
        self.undo_action.setEnabled(loaded and self.session.can_undo)
        self.redo_action.setEnabled(loaded and self.session.can_redo)
        for key, action in self.mode_actions.items():
            action.setEnabled(loaded and (key == 'read' or editable))
        active = bool(editable and (self.pending_add or self.selected_span and self.mode == 'edit' and self.selected_span.editable))
        for control in self.property_controls:
            control.setEnabled(active)
        self.apply_button.setEnabled(active)
        self.autosize_button.setEnabled(active)
        if loaded:
            name = self.session.source.name if self.session.source else 'PDF'
            self.setWindowTitle(f'{"● " if self.session.dirty else ""}{name} — PaperEdit')

    def show_error(self, message):
        self.warning_label.setText(message)
        self.warning_label.show()
        self.statusBar().showMessage(message)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() and u.toLocalFile().lower().endswith('.pdf') for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith('.pdf'):
                self.load_file(url.toLocalFile())
                event.acceptProposedAction()
                break

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.session and self.fit_width:
            if not hasattr(self, '_resize_timer'):
                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(self.render_page)
            self._resize_timer.start(180)

    def closeEvent(self, event):
        if self.word_export_job and self.word_export_job.running:
            choice = QMessageBox.question(self, '正在导出 Word', 'Word 转换仍在进行，要取消转换并关闭吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if choice == QMessageBox.StandardButton.No:
                event.ignore()
                return
            self.word_export_job.cancel()
            self.word_export_job.process.waitForFinished(3000)
        if self._confirm_discard():
            self.pool.clear()
            self.pool.waitForDone()
            event.accept()
        else:
            event.ignore()
