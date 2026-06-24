param(
    [string]$EnvName = "bye",
    [switch]$UseVenv
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PyLauncherVersion {
    param([string]$Version)
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & py "-$Version" -c "import sys" *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $oldPreference
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Step "Be Your Eyes light setup"
Write-Host "Repo: $RepoRoot"

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example." -ForegroundColor Yellow
}

$UseConda = $false
if (-not $UseVenv -and (Test-Command "conda")) {
    $UseConda = $true
}

if ($UseConda) {
    Write-Step "Creating/updating conda environment: $EnvName"
    $envList = conda env list | Out-String
    if ($envList -notmatch "(?m)^\s*$([regex]::Escape($EnvName))\s") {
        conda create -n $EnvName python=3.10 -y
    } else {
        Write-Host "Conda environment already exists: $EnvName"
    }

    function Invoke-EnvPython {
        param([string[]]$Arguments)
        & conda run -n $EnvName python @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Python command failed: $($Arguments -join ' ')" }
    }

    function Invoke-EnvPip {
        param([string[]]$Arguments)
        & conda run -n $EnvName python -m pip @Arguments
        if ($LASTEXITCODE -ne 0) { throw "pip command failed: $($Arguments -join ' ')" }
    }
} else {
    Write-Step "Creating/updating local venv: .venv"
    if (Test-Command "py") {
        if (Test-PyLauncherVersion "3.10") {
            $SystemPythonCommand = "py"
            $SystemPythonArgs = @("-3.10")
        } elseif (Test-PyLauncherVersion "3.9") {
            Write-Host "Python 3.10 was not found; falling back to Python 3.9." -ForegroundColor Yellow
            $SystemPythonCommand = "py"
            $SystemPythonArgs = @("-3.9")
        } else {
            $SystemPythonCommand = "py"
            $SystemPythonArgs = @()
        }
    } elseif (Test-Command "python") {
        $SystemPythonCommand = "python"
        $SystemPythonArgs = @()
    } else {
        throw "Python not found. Install Miniconda or Python 3.9+ first."
    }

    if (-not (Test-Path ".venv")) {
        & $SystemPythonCommand @SystemPythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv. Install Python 3.9+ or Miniconda, then rerun." }
    }

    $PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) {
        throw "Virtual environment Python was not found at $PythonExe. Delete .venv and rerun."
    }

    function Invoke-EnvPython {
        param([string[]]$Arguments)
        & $PythonExe @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Python command failed: $($Arguments -join ' ')" }
    }

    function Invoke-EnvPip {
        param([string[]]$Arguments)
        & $PythonExe -m pip @Arguments
        if ($LASTEXITCODE -ne 0) { throw "pip command failed: $($Arguments -join ' ')" }
    }
}

Write-Step "Upgrading pip tooling"
Invoke-EnvPip @("install", "--upgrade", "pip", "setuptools", "wheel")

Write-Step "Installing light dependencies"
Invoke-EnvPip @("install", "-r", "requirements-core.txt")

Write-Step "Writing heavy-download instructions"
$fence = "```"
$heavy = @"
# Heavy Downloads

Run these yourself when you are ready for multi-GB downloads.

$fence`powershell
cd D:\Be-your-eyes
.\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
.\.venv\Scripts\python.exe -m pip install ultralytics paddlepaddle paddleocr faster-whisper mediapipe
.\.venv\Scripts\python.exe scripts\bootstrap_models.py --skip-deepseek-check
$fence

Optional SAM 3 SOTA segmentation:

1. Request access to Meta's SAM 3 checkpoint on Hugging Face.
2. Download `sam3.pt`.
3. Put it at `D:\Be-your-eyes\sam3.pt` or set `BYE_SAM3_MODEL` in `.env`.

Expected heavy items:

- PyTorch CUDA wheels: large
- PaddlePaddle/PaddleOCR: large
- YOLO/YOLO-World weights: model downloads
- faster-whisper `small`: model download
- MediaPipe hand tracker package: tens of MB
- SAM 3 checkpoint: large, gated download
"@
Set-Content -LiteralPath "HEAVY_DOWNLOADS.md" -Value $heavy -Encoding UTF8

Write-Step "Done"
if ($UseConda) {
    Write-Host "Activate with: conda activate $EnvName" -ForegroundColor Green
} else {
    Write-Host "Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
}
Write-Host "Heavy downloads are listed in HEAVY_DOWNLOADS.md." -ForegroundColor Yellow
