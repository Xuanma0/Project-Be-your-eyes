param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$WsUrl = "ws://127.0.0.1:8000/ws/events",
    [string]$FramesDir = "frames",
    [int]$IntervalMs = 500,
    [int]$RecordDurationSec = 20,
    [string]$OutDir = "artifacts",
    [string]$RunName = "run_baseline",
    [switch]$RealDetBaseline,
    [switch]$RealDepthBaseline,
    [switch]$RealOcrScan,
    [switch]$RealDetActionPlan,
    [switch]$CacheScenario,
    [switch]$TimeoutScenario
)

$ErrorActionPreference = "Stop"

function Join-ProcessArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Args
    )

    $escaped = foreach ($arg in $Args) {
        if ($null -eq $arg) {
            '""'
            continue
        }

        if ($arg -match '[\s"]') {
            '"' + ($arg -replace '"', '\\"') + '"'
        } else {
            $arg
        }
    }

    return [string]::Join(' ', $escaped)
}

function Start-PythonProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "python"
    $psi.Arguments = Join-ProcessArguments -Args $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()
    return $proc
}

function Save-MetricsSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MetricsUrl,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    & curl.exe -sS $MetricsUrl -o $OutputPath
    if ($LASTEXITCODE -ne 0) {
        throw "failed to fetch metrics from $MetricsUrl"
    }
}

function Reset-GatewayRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUrl
    )

    $resetUrl = "{0}/api/dev/reset" -f $BaseUrl.TrimEnd('/')
    $resp = Invoke-RestMethod -Uri $resetUrl -Method Post -TimeoutSec 20
    if ($null -eq $resp -or -not $resp.ok) {
        throw "gateway runtime reset failed via $resetUrl"
    }
}

function Assert-ToolEnabled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUrl,
        [Parameter(Mandatory = $true)]
        [string]$ToolName
    )

    $toolsUrl = "{0}/api/tools" -f $BaseUrl.TrimEnd('/')
    $resp = Invoke-RestMethod -Uri $toolsUrl -Method Get -TimeoutSec 20
    $tools = @()
    if ($null -ne $resp -and $null -ne $resp.tools) {
        $tools = @($resp.tools)
    }
    $hasRealDet = $false
    foreach ($tool in $tools) {
        if ($null -ne $tool.name -and [string]$tool.name -eq $ToolName) {
            $hasRealDet = $true
            break
        }
    }
    if (-not $hasRealDet) {
        throw "$ToolName tool is not enabled."
    }
}

function Set-TimeoutFault {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUrl,
        [Parameter(Mandatory = $true)]
        [string]$ToolName
    )

    $faultUrl = "{0}/api/fault/set" -f $BaseUrl.TrimEnd('/')
    $body = @{
        tool = $ToolName
        mode = "timeout"
        value = $true
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri $faultUrl -Method Post -Body $body -ContentType "application/json" -TimeoutSec 20
    if ($null -eq $resp -or -not $resp.ok) {
        throw "failed to set timeout fault via $faultUrl"
    }
}

function Set-DevIntent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUrl,
        [Parameter(Mandatory = $true)]
        [string]$Intent,
        [Parameter(Mandatory = $true)]
        [int]$DurationMs
    )

    $intentUrl = "{0}/api/dev/intent" -f $BaseUrl.TrimEnd('/')
    $body = @{
        intent = $Intent
        durationMs = $DurationMs
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri $intentUrl -Method Post -Body $body -ContentType "application/json" -TimeoutSec 20
    if ($null -eq $resp -or -not $resp.ok) {
        throw "failed to set dev intent via $intentUrl"
    }
}

$scriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$gatewayDir = Split-Path -Parent $scriptsDir
$outDirAbs = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path $gatewayDir $OutDir }
$framesDirAbs = if ([System.IO.Path]::IsPathRooted($FramesDir)) { $FramesDir } else { Join-Path $gatewayDir $FramesDir }

if ($RealDetActionPlan -and $RunName -eq "run_baseline") {
    $RunName = "run_realdet_actionplan"
} elseif ($CacheScenario -and $RunName -eq "run_baseline") {
    $RunName = "run_cache"
} elseif ($RealDepthBaseline -and $RunName -eq "run_baseline") {
    $RunName = "run_real_depth_baseline"
} elseif ($RealOcrScan -and $RunName -eq "run_baseline") {
    $RunName = "run_realoocr_scan"
} elseif ($RealDetBaseline -and $RunName -eq "run_baseline") {
    $RunName = "run_real_det_baseline"
} elseif ($TimeoutScenario -and $RunName -eq "run_baseline") {
    $RunName = "run_timeout"
}

if (-not (Test-Path $framesDirAbs)) {
    throw "FramesDir not found: $framesDirAbs"
}

New-Item -ItemType Directory -Force -Path $outDirAbs | Out-Null

$wsJsonl = Join-Path $outDirAbs ("{0}.jsonl" -f $RunName)
$reportMd = Join-Path $outDirAbs ("report_{0}.md" -f $RunName)
$metricsBefore = Join-Path $outDirAbs ("metrics_before_{0}.txt" -f $RunName)
$metricsAfter = Join-Path $outDirAbs ("metrics_after_{0}.txt" -f $RunName)
$metricsUrl = "{0}/metrics" -f $BaseUrl.TrimEnd('/')

Write-Host "Reset gateway runtime state -> $BaseUrl"
Reset-GatewayRuntime -BaseUrl $BaseUrl
if ($RealDetBaseline -or $RealDetActionPlan) {
    Write-Host "Validate tool availability -> real_det"
    Assert-ToolEnabled -BaseUrl $BaseUrl -ToolName "real_det"
}
if ($RealDepthBaseline -or $RunName.ToLower().Contains("real_depth")) {
    Write-Host "Validate tool availability -> real_depth"
    Assert-ToolEnabled -BaseUrl $BaseUrl -ToolName "real_depth"
}
if ($CacheScenario) {
    Write-Host "Validate tool availability -> real_det"
    Assert-ToolEnabled -BaseUrl $BaseUrl -ToolName "real_det"
}
if ($RealOcrScan -or $RunName.ToLower().Contains("realoocr")) {
    Write-Host "Validate tool availability -> real_ocr"
    Assert-ToolEnabled -BaseUrl $BaseUrl -ToolName "real_ocr"
    $intentDurationMs = [Math]::Max(5000, ($RecordDurationSec + 5) * 1000)
    Write-Host "Set dev intent -> scan_text (${intentDurationMs}ms)"
    Set-DevIntent -BaseUrl $BaseUrl -Intent "scan_text" -DurationMs $intentDurationMs
}
if ($TimeoutScenario) {
    $timeoutTool = "mock_risk"
    if ($RunName.ToLower().Contains("realoocr")) {
        $timeoutTool = "real_ocr"
    }
    Write-Host "Inject timeout fault -> $timeoutTool"
    Set-TimeoutFault -BaseUrl $BaseUrl -ToolName $timeoutTool
}

Write-Host "[1/4] Start WS record -> $wsJsonl"
Save-MetricsSnapshot -MetricsUrl $metricsUrl -OutputPath $metricsBefore
$recordArgs = @(
    (Join-Path $scriptsDir "ws_record_events.py"),
    "--ws-url", $WsUrl,
    "--output", $wsJsonl,
    "--duration-sec", $RecordDurationSec
)
$recordProc = Start-PythonProcess -WorkingDirectory $gatewayDir -Arguments $recordArgs

Start-Sleep -Seconds 1

Write-Host "[2/4] Send frames -> $framesDirAbs"
$replayArgs = @(
    (Join-Path $scriptsDir "replay_send_frames.py"),
    "--dir", $framesDirAbs,
    "--base-url", $BaseUrl,
    "--interval-ms", $IntervalMs
)
if ($CacheScenario) {
    $replayArgs += @("--repeat-first", "50", "--preserve-old")
}
& python @replayArgs
if ($LASTEXITCODE -ne 0) {
    throw "replay_send_frames.py failed with code $LASTEXITCODE"
}

Write-Host "[3/4] Wait WS recorder"
if ($recordProc.HasExited) {
    Start-Sleep -Milliseconds 150
}

$recordProc.WaitForExit()
$recordStdOut = $recordProc.StandardOutput.ReadToEnd()
$recordStdErr = $recordProc.StandardError.ReadToEnd()
$recordExitCode = [int]$recordProc.ExitCode
$recordProc.Dispose()

if ($recordStdOut) {
    Write-Host ($recordStdOut.TrimEnd())
}
if ($recordStdErr) {
    Write-Warning ($recordStdErr.TrimEnd())
}
if ($recordExitCode -ne 0) {
    throw "ws_record_events.py failed with code $recordExitCode"
}

Write-Host "[4/4] Generate report -> $reportMd"
Save-MetricsSnapshot -MetricsUrl $metricsUrl -OutputPath $metricsAfter
& python (Join-Path $scriptsDir "report_run.py") --metrics-url $metricsUrl --ws-jsonl $wsJsonl --metrics-before $metricsBefore --metrics-after $metricsAfter --output $reportMd
if ($LASTEXITCODE -ne 0) {
    throw "report_run.py failed with code $LASTEXITCODE"
}

if ($TimeoutScenario) {
    $null = Invoke-RestMethod -Uri ("{0}/api/fault/clear" -f $BaseUrl.TrimEnd('/')) -Method Post -TimeoutSec 20
}

Write-Host "Done. Report: $reportMd"
Write-Host "Metrics snapshots: $metricsBefore, $metricsAfter"
