param(
    [string]$Python = ".venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if ($env:OS -ne "Windows_NT") {
    throw "This script must run on Windows. Use GitHub Actions or a Windows machine."
}
$PythonPath = $Python
if (-not [System.IO.Path]::IsPathRooted($PythonPath)) {
    $PythonPath = Join-Path $Root $PythonPath
}
if (-not (Test-Path $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}
& $PythonPath -c "import struct, sys, sysconfig; sys.exit(0 if struct.calcsize('P') == 8 and sys.version_info[:2] == (3, 12) and sysconfig.get_platform() == 'win-amd64' else 1)"
if ($LASTEXITCODE -ne 0) { throw "Use 64-bit Python 3.12 to build this package." }
& $PythonPath -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $PythonPath scripts\create_windows_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }
$dist = Join-Path $Root "dist\PaperEdit2"
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
& $PythonPath -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name PaperEdit2 --icon (Join-Path $Root "artifacts\PaperEdit.ico") `
    --collect-data pymupdf `
    --collect-all pdf2docx --collect-all docx --collect-all numpy --collect-all cv2 `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build\windows") `
    --specpath (Join-Path $Root "build\windows") `
    (Join-Path $Root "launch.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
if (-not (Test-Path (Join-Path $dist "PaperEdit2.exe"))) { throw "EXE missing from build output." }
& $PythonPath scripts\create_demo.py (Join-Path $dist "sample.pdf")
if ($LASTEXITCODE -ne 0) { throw "Sample PDF generation failed." }
Copy-Item README.md (Join-Path $dist "README.md") -Force
$zip = Join-Path $Root "artifacts\PaperEdit2-Windows-x64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Portable package: $zip"
