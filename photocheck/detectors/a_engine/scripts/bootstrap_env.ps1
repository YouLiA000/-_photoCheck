# Create the venv on a pure-ASCII path and install the dependencies.
#
# Why not a .venv inside the project: mediapipe's native layer opens its graph
# files through a single-byte path API, so a non-ASCII directory makes it fail
# with "The path does not exist" and K-07 face detection silently dies.
# See README, environment pitfall #1.
#
# Why the extra uninstall step: rapidocr-onnxruntime declares a dependency on
# opencv-python while mediapipe declares opencv-contrib-python. Both write the
# same cv2 namespace, so a plain install leaves a mixed cv2 whose version
# depends on install order. opencv-contrib-python is a superset, so we keep it
# and remove the plain wheel afterwards. See README, environment pitfall #2.
#
# Usage (from the project root):
#   powershell -ExecutionPolicy Bypass -File scripts/bootstrap_env.ps1

$ErrorActionPreference = "Stop"
$Venv = "C:\venvs\photocheck"
$Py = Join-Path $Venv "Scripts\python.exe"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "==> target venv: $Venv" -ForegroundColor Cyan

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[error] uv not found. Install it: pip install uv (https://docs.astral.sh/uv/)" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $Py)) {
    Write-Host "==> creating venv (Python 3.11)" -ForegroundColor Cyan
    uv venv --python 3.11 $Venv
}

Write-Host "==> installing dependencies" -ForegroundColor Cyan
uv pip install --python $Py -r (Join-Path $Root "requirements.txt")

# Step 2 of the OpenCV policy: rapidocr pulls opencv-python back in, remove it.
# Runs unconditionally and tolerates "not installed" so the script is idempotent.
Write-Host "==> removing the duplicate OpenCV wheel (if present)" -ForegroundColor Cyan
uv pip uninstall --python $Py opencv-python

Write-Host "==> verifying environment" -ForegroundColor Cyan
& $Py (Join-Path $Root "scripts\check_env.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host "[error] environment check failed, see messages above" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "done. use this interpreter:" -ForegroundColor Green
Write-Host "  $Py scripts/smoke_detect.py express_001.png"
