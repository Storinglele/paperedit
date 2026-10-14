# PaperEdit

供本机使用的 PDF 文字编辑器，参考常见桌面 PDF 编辑流程，独立实现。

从 [GitHub Releases](https://github.com/Storinglele/paperedit/releases/latest) 下载：

- `PaperEdit2-macOS-arm64.zip`：Apple Silicon Mac，解压后打开 `PaperEdit2.app`；未进行 Apple 公证。
- `PaperEdit2-Windows-x64.zip`：Windows 10/11 64 位免安装版，解压后打开 `PaperEdit2.exe`，保留 `_internal` 文件夹。
- `SHA256SUMS.txt`：两个压缩包的 SHA-256 校验值。

仓库为私有，请使用有权限的 GitHub 账号下载。发行包均无需安装 Python。

## 使用

构建后的应用位于 `dist/PaperEdit2.app`，双击打开。开发时双击 `run.command`，或运行：

```sh
.venv/bin/python -m pdf_editor artifacts/编辑示例.pdf
```

打开 PDF → 点击原文字 → 直接在页面编辑框里输入 → 点击“完成编辑”（Windows：Ctrl+Enter，Mac：⌘Enter）→ 另存为。右侧可调整字号、颜色和文字框，也可用“自适应文字框”。保存或切换页面时会自动应用正在输入的内容；应用失败会保留输入并提示原因。

添加文字时选择“添加文字”，点击空白位置并输入内容。支持页面缩略图、缩放、搜索、复制、撤销和重做。

## Windows 免安装版

目标版本为 Windows 10/11 64 位免安装版，构建输出是 `PaperEdit2-Windows-x64.zip`。解压后直接双击文件夹中的 `PaperEdit2.exe`，无需安装 Python 或管理员权限；可将整个文件夹复制到 U 盘。请保留 `_internal` 文件夹，不能单独复制 EXE。

Windows 版已在 GitHub Actions 的 Windows 构建机上完成 48 项测试、EXE 构建与 ZIP 解压后的示例 PDF 启动检查。首次实际 Windows 测试发现的 PDF 保存句柄兼容问题已修复。

`artifacts/PaperEdit2-Windows-build-source.zip` 是构建源码包，包含脚本与应用代码，不包含私人 PDF、虚拟环境或 Mac 应用。将它解压到 Windows 构建电脑，安装 64 位 Python 3.12 后双击 `build_windows.cmd` 即可构建。这台构建电脑需要联网下载依赖；软件使用者只需要最终的免安装 ZIP。

在 Windows 机器上构建便携包：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\scripts\build_windows.ps1
```

脚本会自动补齐 PyInstaller，并生成 `artifacts\PaperEdit2-Windows-x64.zip`。当前 macOS 开发机不能可靠地生成或运行 Windows `.exe`；仓库中的 GitHub Actions 工作流可在 Windows 构建机上生成同一个 ZIP，并作为构建产物下载。

文档在本地处理。默认另存新文件，原 PDF 保持不变。导出的新文字是 PDF 文本内容，可以被搜索和提取；原选中文字从页面内容中移除。

## 范围

- 水平文字片段编辑，包括中文。字体优先复用；原字体无法显示新字符时采用替代字体，状态栏会提示。
- STSong-Light 等非嵌入中文字体使用原 PDF 的 Unicode 字体资源；保持字号与原始基线，避免编辑后改用 Droid Sans 而变粗。含同名不同资源、特殊字距、横向缩放或描边的原文字暂不直接替换，提示具体原因。
- 文字过长时根据框宽换行；框高不足会提示扩大编辑框，不会静默截断。
- 替换区域与邻近文字重叠、包含链接或未应用涂黑标记时拒绝替换，保护周围内容。
- 页面整体旋转可阅读与编辑；文字自身竖排或倾斜暂不支持直接编辑。
- 扫描图片可阅读和添加文字，图片内原文字无法编辑；不含 OCR。
- 不含格式转换、图片编辑、段落自动重排、云盘、账号。
- 撤销历史使用 PDF 快照，预算 256 MiB，超限会移除较早历史。
- macOS 应用为 Apple Silicon 本机构建，未进行 Apple 公证；Windows 版为 Windows 10/11 x64 便携包。

## 开发与测试

Python 3.12。依赖安装在项目 `.venv`，不修改系统 Python。

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
bash scripts/build_app.sh
```

PySide6-Essentials 包含所需的 Qt Core、Gui、Widgets。文档引擎：PyMuPDF。第三方组件保持各自许可证；对外发行前需按 PyMuPDF 的 AGPL 或商业许可选择发行方式。

已通过 46 项文档与界面测试，覆盖密集中文表格、页面内编辑、输入未应用时的保存保护、中文和 Unicode 字符、撤销重做、密码与权限、旋转坐标、裁剪页面、旧文字移除和周围图片线条保留。特殊 UserUnit 缩放页面暂为只读，避免坐标误写。PyMuPDF 导入出现 5 条上游 SWIG 弃用警告，测试无失败。此前打包后实际界面验证导出文字可提取，原文字移除、图片和线条保留；本次字体修复另增加了非嵌入字体的界面提交与导出测试，新应用包启动和签名验证通过。

字体修复使用本地原 PDF 验证“转账存入”改为“转账存取”：保存后字体仍为 STSong-Light、8 pt，基线不变；未改的“转账存”三个字在 8 倍渲染下像素完全一致。结果记录在 `artifacts/font-fidelity-report.json`。输入框暂用系统字体预览，点击“完成编辑”后显示原 PDF 字体的实际渲染。此前已经用替代字体保存的文本无法自动恢复原字体，请从原始 PDF 重新编辑。

修改后的较长单行文字会向空白处扩展编辑框，到相邻文字前停止；可拖动紫色框顶部的柄移动位置、右下角的柄调整大小。加密 PDF 的导出继续使用本次输入的打开密码，并保留权限设置。
