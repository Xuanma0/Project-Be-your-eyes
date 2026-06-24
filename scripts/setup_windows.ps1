param(
    [string]$EnvName = "bye",
    [switch]$UseVenv,
    [switch]$CpuTorch,
    [switch]$NoModelDownload,
    [switch]$SkipDeepSeekCheck
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

Write-Step "Be Your Eyes one-click setup"
Write-Host "Repo: $RepoRoot"

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill DEEPSEEK_API_KEY after setup." -ForegroundColor Yellow
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
        throw "Virtual environment Python was not found at $PythonExe. Delete .venv and rerun the script."
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

Write-Step "Installing PyTorch"
if ($CpuTorch) {
    Invoke-EnvPip @("install", "torch", "torchvision", "torchaudio")
} else {
    # CUDA 11.8 wheels are a stable fit for RTX 2080Ti on Windows.
    Invoke-EnvPip @("install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu118")
}

Write-Step "Installing Python dependencies"
Invoke-EnvPip @("install", "-r", "requirements.txt")

Write-Step "Checking FFmpeg"
if (Test-Command "ffmpeg") {
    ffmpeg -version | Select-Object -First 1
} else {
    Write-Host "FFmpeg was not found in PATH." -ForegroundColor Yellow
    Write-Host "Install it with one of these, then rerun if audio/video tooling complains:" -ForegroundColor Yellow
    Write-Host "  winget install Gyan.FFmpeg"
    Write-Host "  choco install ffmpeg"
}

if (-not $NoModelDownload) {
    Write-Step "Downloading detector/open-vocabulary/OCR/ASR models"
    $deepseekFlag = ""
    if ($SkipDeepSeekCheck) {
        $deepseekFlag = "--skip-deepseek-check"
    }
    if ($SkipDeepSeekCheck) {
        Invoke-EnvPython @("scripts/bootstrap_models.py", "--skip-deepseek-check")
    } else {
        Invoke-EnvPython @("scripts/bootstrap_models.py")
    }
} else {
    Write-Step "Skipping model downloads because -NoModelDownload was set"
}

Write-Step "Done"
if ($UseConda) {
    Write-Host "Activate with: conda activate $EnvName" -ForegroundColor Green
} else {
    Write-Host "Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
}
Write-Host "Then edit .env and set DEEPSEEK_API_KEY." -ForegroundColor Green
