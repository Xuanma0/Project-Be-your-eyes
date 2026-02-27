param(
    [switch]$usb,
    [switch]$lan,
    [switch]$withInference,
    [switch]$dryRun,
    [int]$port = 8000,
    [string]$gatewayHost = ""
)

$ErrorActionPreference = "Stop"

if ($usb -and $lan) {
    throw "Use either --usb or --lan, not both."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
Set-Location $repoRoot

function Set-DefaultEnv {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Value
    )

    $current = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($current)) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
        Write-Host "[env default] $Name=$Value"
    } else {
        Write-Host "[env keep]    $Name=$current"
    }
}

if ([string]::IsNullOrWhiteSpace($gatewayHost)) {
    if ($lan) {
        $gatewayHost = "0.0.0.0"
    } else {
        $gatewayHost = "127.0.0.1"
    }
}

Set-DefaultEnv "BYES_OCR_BACKEND" "mock"
Set-DefaultEnv "BYES_RISK_BACKEND" "mock"
Set-DefaultEnv "BYES_SEG_BACKEND" "mock"
Set-DefaultEnv "BYES_DEPTH_BACKEND" "mock"
Set-DefaultEnv "BYES_SLAM_BACKEND" "mock"
Set-DefaultEnv "BYES_PLANNER_PROVIDER" "reference"
Set-DefaultEnv "BYES_GATEWAY_PROFILE" "local"

if ($usb) {
    $adb = Get-Command adb -ErrorAction SilentlyContinue
    if ($null -eq $adb) {
        Write-Warning "adb not found in PATH. Install Android platform-tools or run without --usb."
    } else {
        Write-Host "== adb devices =="
        & adb devices
        Write-Host "== adb reverse tcp:$port tcp:$port =="
        & adb reverse ("tcp:{0}" -f $port) ("tcp:{0}" -f $port)
        Write-Host "== adb reverse --list =="
        & adb reverse --list
    }
}

Write-Host "== Local IPv4 candidates =="
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.PrefixOrigin -ne 'WellKnown'
    } |
    Select-Object InterfaceAlias, IPAddress |
    Format-Table -AutoSize

Write-Host "== Quest3 Smoke =="
Write-Host "Gateway host: $gatewayHost"
Write-Host "Gateway port: $port"
Write-Host "Next: launch Quest app -> wait for SelfTest PASS on panel."

$devUpArgs = @("Gateway/scripts/dev_up.py", "--host", $gatewayHost, "--gateway-only", "--gateway-port", "$port")
if ($withInference) {
    $devUpArgs += "--with-inference"
}

Write-Host "== Running: python $($devUpArgs -join ' ') =="
if ($dryRun) {
    Write-Host "[dry-run] skipped process launch."
    exit 0
}

python @devUpArgs
