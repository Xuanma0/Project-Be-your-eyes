param(
    [switch]$InstallQwenAsr,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Repo ".venv-voice"
$VoiceDataDir = Join-Path $Repo "data\voice"

function Resolve-Python {
    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.10"),
        @("py", "-3.9"),
        @("python")
    )

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $args = @()
        if ($candidate.Count -gt 1) {
            $args = $candidate[1..($candidate.Count - 1)]
        }

        try {
            $version = & $exe @args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version) {
                return @{ Exe = $exe; Args = $args; Version = [string]$version }
            }
        } catch {
        }
    }

    throw "Python not found. For Qwen3-ASR, install Python 3.12, then rerun this script."
}

function Stop-VoiceSidecar {
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match "python" -and (
            $_.CommandLine -match "uvicorn voice_service.main:app" -or
            $_.CommandLine -match [regex]::Escape($VenvDir)
        )
    }
    foreach ($proc in $processes) {
        Write-Host "Stopping voice sidecar process $($proc.ProcessId)"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }

    try {
        $listeners = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
        foreach ($listener in $listeners) {
            Write-Host "Stopping process on port 8010: $($listener.OwningProcess)"
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {
    }

    Start-Sleep -Seconds 1
}

function Remove-TreeWithRetry {
    param([string]$Path)

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
            return
        } catch {
            if ($attempt -eq 5) {
                throw
            }
            Write-Host "Remove failed; retrying after stopping sidecar ($attempt/5)"
            Stop-VoiceSidecar
            Start-Sleep -Seconds 1
        }
    }
}

$Python = Resolve-Python
Write-Host "==> Voice sidecar setup"
Write-Host "Repo: $Repo"
Write-Host "Python: $($Python.Exe) $($Python.Args -join ' ') ($($Python.Version))"
if (-not ($Python.Version -eq "3.12")) {
    Write-Host "Warning: Qwen3-ASR officially recommends Python 3.12. This setup can still run fallback local TTS."
}
if ($InstallQwenAsr -and -not ($Python.Version -eq "3.12")) {
    throw "Qwen3-ASR setup should use Python 3.12. Install Python 3.12, then rerun with -InstallQwenAsr -Recreate."
}

Write-Host ""
Write-Host "==> Creating/updating local voice venv: .venv-voice"
if ($Recreate -and (Test-Path $VenvDir)) {
    Stop-VoiceSidecar
    $resolvedRepo = (Resolve-Path $Repo).Path
    $resolvedVenvParent = (Resolve-Path (Split-Path -Parent $VenvDir)).Path
    if ($resolvedVenvParent -ne $resolvedRepo) {
        throw "Refusing to recreate venv outside repo: $VenvDir"
    }
    Remove-TreeWithRetry -Path $VenvDir
}
& $Python.Exe @($Python.Args + @("-m", "venv", $VenvDir))
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($VenvVersion -ne $Python.Version) {
    throw ".venv-voice is Python $VenvVersion, but selected Python is $($Python.Version). Rerun with -Recreate to rebuild it."
}

Write-Host ""
Write-Host "==> Installing lightweight voice service dependencies"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install fastapi "uvicorn[standard]" requests pyttsx3 numpy soundfile modelscope
New-Item -ItemType Directory -Force -Path $VoiceDataDir | Out-Null

if ($InstallQwenAsr) {
    Write-Host ""
    Write-Host "==> Installing Qwen3-ASR runtime"
    & $VenvPython -m pip install -U qwen-asr
} else {
    Write-Host ""
    Write-Host "Qwen3-ASR runtime is optional and larger. Install it with:"
    Write-Host "  .\scripts\setup_voice_sidecar.ps1 -InstallQwenAsr"
}

Write-Host ""
Write-Host "IndexTTS2 model weights are already expected under:"
Write-Host "  $Repo\models\IndexTTS-2"
Write-Host "To enable true IndexTTS2 synthesis, install the official runtime into this voice env or run the sidecar from an IndexTTS2 env."
Write-Host "Recommended official code setup:"
Write-Host "  git clone https://github.com/index-tts/index-tts third_party\index-tts"
Write-Host "  cd third_party\index-tts"
Write-Host "  pip install -U uv"
Write-Host "  uv sync --extra webui"
Write-Host ""
Write-Host "Put a 3-10 second Chinese reference voice wav at:"
Write-Host "  $Repo\data\voice\reference.wav"
Write-Host ""
Write-Host "Done. Start the sidecar with:"
Write-Host "  .\scripts\run_voice_sidecar.ps1"
