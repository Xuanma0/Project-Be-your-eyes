param(
    [switch]$Foreground,
    [switch]$AllowModelDownload
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Repo ".venv-tracker\Scripts\python.exe"
$LogDir = Join-Path $Repo "data\logs"

if (-not (Test-Path $VenvPython)) {
    throw ".venv-tracker was not found. Run .\scripts\setup_tracker_sidecar.ps1 first."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if (-not $env:BYE_TRACKER_BACKEND) { $env:BYE_TRACKER_BACKEND = "cotracker3_online" }
if (-not $env:BYE_TRACKER_DEVICE) { $env:BYE_TRACKER_DEVICE = "cuda" }
if (-not $env:BYE_TRACKER_MAX_WIDTH) { $env:BYE_TRACKER_MAX_WIDTH = "384" }
if (-not $env:BYE_TRACKER_HYBRID_CV) { $env:BYE_TRACKER_HYBRID_CV = "1" }
if (-not $env:BYE_TRACKER_OPENCV_BACKEND) { $env:BYE_TRACKER_OPENCV_BACKEND = "lk" }
if ($AllowModelDownload) { $env:BYE_TRACKER_ALLOW_DOWNLOAD = "1" }

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match "python" -and $_.CommandLine -match "uvicorn tracker_service.main:app"
}
foreach ($proc in $existing) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

if ($Foreground) {
    Set-Location $Repo
    & $VenvPython -m uvicorn tracker_service.main:app --host 127.0.0.1 --port 8020
    exit $LASTEXITCODE
}

$outLog = Join-Path $LogDir "tracker.out.log"
$errLog = Join-Path $LogDir "tracker.err.log"
Start-Process `
    -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "tracker_service.main:app", "--host", "127.0.0.1", "--port", "8020", "--no-access-log") `
    -WorkingDirectory $Repo `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

Start-Sleep -Seconds 2
Write-Host "Tracker sidecar started at http://127.0.0.1:8020"
Write-Host "Status: http://127.0.0.1:8020/status"
