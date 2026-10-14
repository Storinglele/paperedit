# PDF 转 Word 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本计划由当前会话直接执行。

**Goal:** 在 PaperEdit 中导出本地、可编辑的 Word 文档，并验证 Mac 与 Windows 免安装应用的实际转换能力。

**Architecture:** Qt 界面控制独立转换工作进程，工作进程读取点击导出时的 PDF 快照。转换层完成文字与图像预检、DOCX 生成与验证；父进程在工作进程成功退出后提交目标文件，取消时不提交。

**Tech Stack:** Python 3.12、PyMuPDF 1.27.2.2、PySide6-Essentials 6.10.2、pdf2docx 0.5.13、python-docx、PyInstaller 6.19.0。

**Spec:** [功能设计](../specs/2026-10-14-pdf-to-word-design.md)

## Global Constraints

- 第一版处理能够提取文字的 PDF，生成可在 Microsoft Word 和 WPS 中继续编辑的 `.docx`。
- 文件在本地处理，兼容现有 macOS Apple Silicon 应用与 Windows x64 免安装包。
- 本版不包含 OCR、批量转换、指定页码转换、Word 转 PDF 或其他格式。
- 输出文字不能用整页截图代替；不承诺与 UPDF 的结果或原 PDF 完全一致。
- 原 PDF、撤销历史与 PDF 已保存标记不因 Word 导出而改变。
- 禁用转换引擎默认的忽略页面错误行为。
- 成功前不覆盖已有目标文件；失败和取消均清理临时产物。
- 不上传私人 PDF，不将正文或密码写入日志或公共样例。
- README 面向最终能力与使用，不加入修复经过。

## Review Focus

- 中文路径、已有 Word 文件及 Windows 文件句柄：成功时正常替换，失败或取消时原文件字节不变；归属任务 1、2。
- 加密 PDF 的提取权限与所有者认证：不能利用解密快照绕过权限；归属任务 1、3。
- 混合扫描页和完全空白页：图像文字不可编辑时告知用户，空白页不误报；归属任务 1、3。
- 取消与工作进程成功几乎同时发生：父进程取消标志优先，未获成功提交前不得修改目标；归属任务 2。
- 冻结程序缺失原生依赖、DOCX 模板或工作入口：两平台解压后的程序必须实际完成转换；归属任务 4。

---

## Task 1: 转换层、权限和内容测试

**Files:** 新增 `pdf_editor/conversion.py`、`tests/test_conversion.py`；修改 `pdf_editor/document.py`、`requirements.txt`。

**Interfaces:**
- `DocumentSession.can_extract: bool` 与 `DocumentSession.password_protected: bool` 保留源文档的认证和权限信息。
- `inspect_pdf(data: bytes) -> ConversionInfo`；结果包含总页数、含文字页数、图片但无文字的页码。
- `write_docx(data: bytes, staged_path: Path) -> None` 生成并验证暂存文件；不能提交最终目标。
- `validate_docx(path: Path) -> None` 检查 ZIP、必需部件及 Word 文档可解析性。
- `publish_docx(staged_path: Path, destination: Path) -> None` 验证、同步并原子替换。
- 以上失败统一抛出 `ConversionError`，向界面提供简洁中文原因。

- [ ] 写真实 PDF/DOCX 测试：`test_editable_chinese_english_images_and_tables` 独立断言中英文文字、图片和 2×2 网格表格内容；`test_multipage_content_and_page_sections` 验证两页内容和节结构；`test_export_keeps_source_history_and_dirty_state` 验证当前修改、原 PDF 字节、撤销和未保存标记。
- [ ] 写预检与权限测试：扫描件拒绝、混合页报告图片页、空白页不误报、损坏 PDF 拒绝；所有者可提取，普通密码按 `PDF_PERM_COPY` 处理。写目标中文路径、损坏 DOCX、不存在目录和失败时既有文件不变的测试。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_conversion.py -q`，确认因缺失转换功能失败，再实现代码。
- [ ] 用 `uv pip install --python .venv/bin/python -r requirements-dev.txt` 安装固定版本依赖；`pdf2docx==0.5.13`，`python-docx` 选择并记录经实际测试的固定版本。
- [ ] 实现预检和转换；使用 `Converter(stream=data)`，关闭 OCR、多进程及忽略页面错误。始终关闭转换器，防止生成日志泄露 PDF 内容。
- [ ] 运行转换测试和现有文档测试，确认全部通过，检查 Word XML 中实际可编辑文字与表格。
- [ ] 将本任务源码和测试同步到现有干净 GitHub checkout，只提交这次变更，不处理原工作目录已有的索引锁。

## Task 2: 异步工作进程与取消

**Files:** 新增 `pdf_editor/conversion_worker.py`、`pdf_editor/conversion_job.py`、`tests/test_conversion_job.py`；修改 `pdf_editor/__main__.py`。

**Interfaces:**
- `worker_main(job_dir: Path) -> int`：读取私有目录中的 PDF 快照，输出逐行 JSON 协议；预检后发送 `ready`，从标准输入接收包含暂存路径的 `convert` 指令，完成后发送 `complete`。
- `ConversionJob(QObject)`：`start(data: bytes) -> None`、`proceed(destination: Path) -> None`、`cancel() -> None`；提供 `ready(object)`、`succeeded(str)`、`failed(str)`、`finished()` 信号及 `running: bool`。
- 内部入口 `--paperedit-convert-worker <job_dir>` 在创建 QApplication 前处理；源码模式使用当前 Python，冻结模式使用当前应用可执行文件。
- 父进程创建目标目录下的临时 DOCX，只有收到完成结果并确认退出码为 0、任务未取消时调用 `publish_docx`。

- [ ] 写进程集成测试：`test_real_worker_exports_docx` 验证真实工作进程输出；`test_cancel_keeps_existing_destination` 验证取消时既有目标内容和临时产物；`test_invalid_pdf_reports_failure_and_cleans_up` 验证错误和清理。
- [ ] 增加任务竞态及退出测试：取消标记先设置后到达成功结果不能提交；非零退出和损坏输出不能替换目标；一次任务只发送一次完成信号。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_conversion_job.py -q`，观察缺失行为导致的失败。
- [ ] 实现 QProcess 控制器、缓冲逐行 JSON 解析和工作进程。第三方库输出从协议通道分离；UI 不显示正文或完整内部异常。
- [ ] 使用私有缓存任务目录与存活锁；创建 Unix 目录权限 0700、快照权限 0600。完成、失败、取消均删除产物；启动清理已失去存活锁的遗留任务，保留其他活跃实例。
- [ ] 执行任务测试和转换测试；验证事件循环可响应、工作进程退出、暂存句柄关闭与源文件不变，然后提交。

## Task 3: 导出界面与关闭流程

**Files:** 修改 `pdf_editor/window.py`、`tests/test_ui.py`。

**Interfaces:**
- `EditorWindow.export_word_dialog()` 先应用待提交编辑，再检查源权限并启动预检。
- `ConversionJob.ready` 后展示混合扫描页及密码保护提示，获取 `.docx` 路径并调用 `proceed`；取消对话框则调用 `cancel`。
- `EditorWindow.word_export_job` 保存任务引用；导出中禁用重复导出并展示忙碌状态。

- [ ] 写 `test_word_export_contains_pending_edit`，真实导出后在 DOCX 中找到修改内容，PDF 仍为未保存状态；仅替换系统文件对话框，不替换转换器。
- [ ] 写入口状态、编辑无效时阻止导出、扫描件错误反馈、加密保护提示取消、已有任务禁止重复启动的测试。
- [ ] 写关闭流程测试：继续等待保持窗口；取消后工作进程退出、临时文件删除；仍保留原有 PDF 保存询问。
- [ ] 先执行相关 UI 测试看到失败，再实现工具栏和文件菜单入口、默认同名 `.docx`、后缀补齐与已有文件覆盖确认。
- [ ] 实现忙碌进度、错误提示、成功路径和打开所在文件夹。成功后恢复入口；关闭时先询问等待或取消转换，再沿用 PDF 保存逻辑。
- [ ] 运行 `.venv/bin/python -m pytest -q`，完整现有测试和新增测试全部通过后提交。

## Task 4: 两平台打包、样例视觉验证和使用说明

**Files:** 修改 `scripts/build_app.sh`、`scripts/build_windows.ps1`、`.github/workflows/build-windows.yml`、`README.md`；新增 `scripts/check_packaged_conversion.py` 和公开生成样例脚本。

**Interfaces:**
- 打包检查脚本接收应用可执行文件路径，创建人工 PDF、通过内部工作进程入口生成 DOCX并检查内容；内部入口必须与任务 2 一致。
- 新依赖、DOCX 默认模板和 NumPy/OpenCV 原生库随包分发。

- [ ] 生成无私人信息的两页中英文、图片和表格样例；保留相应 PDF 和 DOCX 供视觉对照。
- [ ] 构建 Mac 应用并执行 `.venv/bin/python scripts/check_packaged_conversion.py dist/PaperEdit2.app/Contents/MacOS/PaperEdit2`；首次缺依赖时保留失败证据，修正收集规则后再次确认实际转换成功。
- [ ] 更新 Windows CI，在解压 ZIP 后保留现有启动检查，并运行同一打包转换脚本；确认 Windows EXE 能实际完成转换。
- [ ] README 增加转换入口、可编辑 DOCX、扫描件不支持、复杂排版可能调整、密码保护提示；移除已过时的“暂不支持格式转换”和“私有仓库”说明。
- [ ] 使用可用办公渲染工具或 Word/WPS 检查样例，不存在工具时明确记录验证限制；不能仅因 XML 正确就宣称视觉排版一致。
- [ ] 运行完整测试、检查 Git diff，再构建 Mac ZIP、计算 SHA-256；Windows ZIP 由成功的 CI 产出。保留原 v0.1.0 以便回退。
- [ ] 提交并推送已验证代码，在原有发布授权范围内发布新版本和两平台包；若发布需要额外授权，先准备好所有可审阅产物再提出。

## 计划自审

本计划覆盖设计中的范围、权限、扫描页提示、后台转换、取消清理、原子输出、用户界面、两平台实际转换、样例检查及 README。取消与成功竞态由父进程统一提交避免；转换层不自行覆盖最终路径。全部验证使用人工文档，私人资料不进入仓库或 CI。
