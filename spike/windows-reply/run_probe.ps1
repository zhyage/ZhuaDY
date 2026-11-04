# Run the Douyin reply probe on Windows.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\run_probe.ps1
#   powershell -ExecutionPolicy Bypass -File .\run_probe.ps1 -StartChromeOnly
#
# The script starts a dedicated Chrome profile with CDP on port 9222, then runs
# probe_reply.py. It never closes the user's main Chrome. Log in via QR in the
# dedicated window before running the probe.

param(
    [string]$ChromePath = "",
    [string]$ProfileDir = "$env:USERPROFILE\douyin-reply-profile",
    [int]$Port = 9222,
    [string]$Python = "python",
    [switch]$StartChromeOnly,
    [switch]$SkipProbe
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Find-Chrome {
    if ($ChromePath -and (Test-Path $ChromePath)) { return $ChromePath }
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    throw "Chrome not found. Pass -ChromePath 'C:\path\to\chrome.exe'."
}

function Test-Cdp {
    try {
        Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

$chrome = Find-Chrome
Write-Host "Chrome: $chrome"
Write-Host "Profile: $ProfileDir"
Write-Host "CDP port: $Port"

if (-not (Test-Cdp)) {
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
    Write-Host "Starting Chrome with CDP..."
    Start-Process -FilePath $chrome -ArgumentList @(
        "--remote-debugging-port=$Port",
        "--user-data-dir=`"$ProfileDir`"",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "https://www.douyin.com/"
    )
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not (Test-Cdp)) {
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Cdp)) {
        throw "CDP is not reachable on port $Port. If Chrome opened with the wrong profile, close that dedicated window and retry."
    }
} else {
    Write-Host "CDP already reachable on port $Port."
}

if ($StartChromeOnly) {
    Write-Host ""
    Write-Host "Chrome is ready. Log in via QR in the dedicated window, then rerun without -StartChromeOnly."
    exit 0
}

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python not found: $Python. Pass -Python 'C:\path\to\python.exe'."
}

Write-Host "Checking Playwright..."
$playwrightOk = $false
try {
    & $Python -c "import playwright" *> $null
    $playwrightOk = ($LASTEXITCODE -eq 0)
} catch {
    $playwrightOk = $false
}
if (-not $playwrightOk) {
    throw "Playwright is not installed for '$Python'. Run: $Python -m pip install playwright"
}

if ($SkipProbe) { exit 0 }

$probeArgs = @(
    "probe_reply.py",
    "--targets", "targets.json"
)

Write-Host "Running probe..."
$code = 0
try {
    & $Python @probeArgs
    $code = $LASTEXITCODE
} catch {
    Write-Host "Probe failed: $($_.Exception.Message)"
    $code = 1
}
Write-Host "Probe exit code: $code"

if (Test-Path "$root\out") {
    $latest = Get-ChildItem -Directory "$root\out" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        Write-Host ""
        Write-Host "Output directory: $($latest.FullName)"
        Get-ChildItem $latest.FullName | Select-Object Name, Length | Format-Table
        Write-Host "Send back report.md and summary.json only. Do not send responses/ or cookies."
    }
}

exit $code
