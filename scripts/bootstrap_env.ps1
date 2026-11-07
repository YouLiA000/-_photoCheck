param(
    [string]$PythonPath = "",
    [string]$VenvPath = "",
    [switch]$InstallDev
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $PythonPath) {
    $PythonPath = $env:PHOTOCHECK_PYTHON
}
if (-not $PythonPath) {
    throw "Pass -PythonPath or set PHOTOCHECK_PYTHON to a Python 3.11 executable."
}
$BasePython = (Get-Command $PythonPath -ErrorAction SilentlyContinue).Source
if (-not $BasePython) {
    throw "Python executable not found: $PythonPath"
}

if (-not $VenvPath) {
    $VenvPath = Join-Path $Root ".venv"
}
$VenvPath = [System.IO.Path]::GetFullPath($VenvPath)
$Python = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    & $BasePython -m venv $VenvPath
}

& $Python -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Runtime dependency install failed."
}
if ($InstallDev) {
    & $Python -m pip install -r (Join-Path $Root "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Development dependency install failed."
    }
}

# rapidocr declares opencv-python even though the project requires contrib.
# Rebuild the OpenCV namespace with contrib only after dependency resolution.
& $Python -m pip uninstall -y opencv-python opencv-contrib-python
& $Python -m pip install "opencv-contrib-python==4.10.0.84"
if ($LASTEXITCODE -ne 0) {
    throw "OpenCV normalization failed."
}

& $Python (Join-Path $Root "photocheck\scripts\check_environment.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output $Python
