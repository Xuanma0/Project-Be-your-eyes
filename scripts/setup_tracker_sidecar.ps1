param(
    [switch]$InstallTorchCu118,
    [switch]$InstallEfficientSam2,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Repo ".venv-tracker"

function Resolve-Python {
    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("py", "-3.10"),
        @("python")
    )
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $args = @()
        if ($candidate.Count -gt 1) { $args = $candidate[1..($candidate.Count - 1)] }
        try {
            $version = & $exe @args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version) {
                $minor = [int](([string]$version).Split(".")[1])
                if ($minor -ge 10) {
                    return @{ Exe = $exe; Args = $args; Version = [string]$version }
                }
            }
        } catch {
        }
    }
    throw "Python 3.10+ not found. Install Python 3.12 or 3.11 first."
}

function Stop-TrackerSidecar {
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match "python" -and (
            $_.CommandLine -match "uvicorn tracker_service.main:app" -or
            $_.CommandLine -match [regex]::Escape($VenvDir)
        )
    }
    foreach ($proc in $processes) {
        Write-Host "Stopping tracker sidecar process $($proc.ProcessId)"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    try {
        $listeners = Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {
    }
    Start-Sleep -Seconds 1
}

$Python = Resolve-Python
Write-Host "==> Tracker sidecar setup"
Write-Host "Repo: $Repo"
Write-Host "Python: $($Python.Exe) $($Python.Args -join ' ') ($($Python.Version))"

if ($Recreate -and (Test-Path $VenvDir)) {
    Stop-TrackerSidecar
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

Write-Host ""
Write-Host "==> Creating/updating local tracker venv: .venv-tracker"
& $Python.Exe @($Python.Args + @("-m", "venv", $VenvDir))
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install fastapi "uvicorn[standard]" numpy opencv-python pillow requests einops timm tqdm

if ($InstallTorchCu118) {
    Write-Host ""
    Write-Host "==> Installing PyTorch CUDA 11.8 runtime for RTX 2080Ti"
    & $VenvPython -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
} else {
    Write-Host ""
    Write-Host "Torch is the large dependency. Install it when ready with:"
    Write-Host "  .\scripts\setup_tracker_sidecar.ps1 -InstallTorchCu118"
}

if (-not (Test-Path (Join-Path $Repo "third_party"))) {
    New-Item -ItemType Directory -Path (Join-Path $Repo "third_party") | Out-Null
}
if (-not (Test-Path (Join-Path $Repo "third_party\Efficient-SAM2"))) {
    Write-Host ""
    Write-Host "==> Cloning Efficient-SAM2 official repo"
    git clone --depth 1 https://github.com/jingjing0419/Efficient-SAM2 (Join-Path $Repo "third_party\Efficient-SAM2")
}

if ($InstallEfficientSam2) {
    Write-Host ""
    Write-Host "==> Installing Efficient-SAM2 official code into tracker env"
    & $VenvPython -m pip install -e (Join-Path $Repo "third_party\Efficient-SAM2")
} else {
    Write-Host ""
    Write-Host "Efficient-SAM2 is the 2026 VOS calibrator. Install its code after torch with:"
    Write-Host "  .\scripts\setup_tracker_sidecar.ps1 -InstallEfficientSam2"
    Write-Host "Then download tiny/small SAM2.1 base checkpoints only if you want mask calibration."
}

Write-Host ""
Write-Host "Done. Start the tracker sidecar with:"
Write-Host "  .\scripts\run_tracker_sidecar.ps1 -AllowModelDownload"
