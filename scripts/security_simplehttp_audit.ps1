param(
    [string]$AlertSourceIp = "122.96.28.176",
    [string]$AlertDestinationIp = "101.5.189.69",
    [int]$AlertPort = 2222,
    [string]$Repo = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "SilentlyContinue"

function Section($Name) {
    Write-Host ""
    Write-Host "==> $Name"
}

Section "Alert"
[pscustomobject]@{
    SourceIp = $AlertSourceIp
    DestinationIp = $AlertDestinationIp
    DestinationPort = $AlertPort
    Repo = $Repo
} | Format-List

Section "Current public egress IP"
foreach ($url in @("https://api.ipify.org", "https://icanhazip.com")) {
    try {
        $ip = (Invoke-RestMethod -Uri $url -TimeoutSec 8).ToString().Trim()
        Write-Host "$url => $ip"
    } catch {
        Write-Host "$url => unavailable"
    }
}

Section "Current TCP state for alert port"
Get-NetTCPConnection -LocalPort $AlertPort -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, State, OwningProcess |
    Format-Table -AutoSize

Section "Current connections from alert source IP"
Get-NetTCPConnection -RemoteAddress $AlertSourceIp -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, State, OwningProcess |
    Format-Table -AutoSize

Section "Listening ports with process names"
$rows = @()
foreach ($conn in (Get-NetTCPConnection -State Listen | Sort-Object LocalPort, LocalAddress)) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    $rows += [pscustomobject]@{
        LocalAddress = $conn.LocalAddress
        LocalPort = $conn.LocalPort
        PID = $conn.OwningProcess
        Process = $proc.ProcessName
        Path = $proc.Path
    }
}
$rows | Format-Table -AutoSize

Section "Repository clues"
if (Test-Path $Repo) {
    rg -n "SimpleHTTP|SimpleHTTPRequestHandler|http\.server|directory listing|autoindex|Options Indexes|0\.0\.0\.0|$AlertPort|$AlertSourceIp|$AlertDestinationIp" `
        $Repo `
        --glob "!models/**" `
        --glob "!third_party/**" `
        --glob "!.venv*/**" `
        --glob "!data/logs/evidence.jsonl" `
        --glob "!data/logs/snapshots/**" 2>$null |
        Select-Object -First 120
}

Section "Shell history clues"
$historyFiles = @(
    (Join-Path $env:APPDATA "Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"),
    (Join-Path $env:USERPROFILE ".bash_history"),
    (Join-Path $env:USERPROFILE ".zsh_history")
) | Where-Object { Test-Path $_ }
foreach ($file in $historyFiles) {
    Write-Host "-- $file"
    Select-String -LiteralPath $file -Pattern "$AlertSourceIp|$AlertDestinationIp|$AlertPort|SimpleHTTP|http\.server|SimpleHTTPRequestHandler|python.*-m.*http|ngrok|frp|cloudflared|ssh.*-[RL]" -CaseSensitive:$false |
        Select-Object -Last 80 |
        ForEach-Object { $_.Line }
}

Section "Sensitive env surface"
$envPath = Join-Path $Repo ".env"
if (Test-Path $envPath) {
    $names = Get-Content -LiteralPath $envPath |
        Where-Object { $_ -match "^\s*[^#=]+=" } |
        ForEach-Object { ($_ -split "=", 2)[0].Trim() } |
        Sort-Object -Unique
    [pscustomobject]@{
        EnvExists = $true
        VariableNames = ($names -join ", ")
    } | Format-List
} else {
    [pscustomobject]@{ EnvExists = $false } | Format-List
}

Section "Admin hardening command"
Write-Host "Run this in an Administrator PowerShell if this host should never expose TCP ${AlertPort}:"
Write-Host "New-NetFirewallRule -DisplayName 'Be-your-eyes: block inbound TCP $AlertPort' -Direction Inbound -Action Block -Protocol TCP -LocalPort $AlertPort -Profile Any"
