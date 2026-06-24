param(
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Repo ".venv-voice\Scripts\python.exe"
$LogDir = Join-Path $Repo "data\logs"

if (-not (Test-Path $VenvPython)) {
    throw ".venv-voice was not found. Run .\scripts\setup_voice_sidecar.ps1 first."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$env:BYE_INDEXTTS_MODEL_DIR = Join-Path $Repo "models\IndexTTS-2"
$env:BYE_QWEN_ASR_MODEL_DIR = Join-Path $Repo "models\Qwen3-ASR-0.6B"
$env:BYE_TTS_PROMPT_WAV = Join-Path $Repo "data\voice\reference.wav"

if ($Foreground) {
    & $VenvPython -m uvicorn voice_service.main:app --host 127.0.0.1 --port 8010
    exit $LASTEXITCODE
}

$outLog = Join-Path $LogDir "voice.out.log"
$errLog = Join-Path $LogDir "voice.err.log"

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match "python" -and $_.CommandLine -match "uvicorn voice_service.main:app"
}
foreach ($proc in $existing) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Process `
    -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "voice_service.main:app", "--host", "127.0.0.1", "--port", "8010", "--no-access-log") `
    -WorkingDirectory $Repo `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

Write-Host "Voice sidecar started at http://127.0.0.1:8010"
Write-Host "Logs:"
Write-Host "  $outLog"
Write-Host "  $errLog"
