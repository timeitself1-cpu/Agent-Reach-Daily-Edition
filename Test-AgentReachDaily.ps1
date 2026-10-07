<#
.SYNOPSIS
    Agent Reach Daily self-test on this PC (real Windows, real Ollama, real news).

.DESCRIPTION
    Runs tests\daily_selftest.py with the project's own environment (.venv):
      - checks Python, Tk and the launchers (Desktop / Start menu shortcuts, AgentReachDaily.cmd, .pyw)
      - checks the real Ollama (running, missing model, nothing listening, another program on the port)
      - runs the offline test suite (it opens and closes small windows for a minute or two)
      - runs real refreshes in a scratch folder under %TEMP%: cancel at once, cancel halfway, a full
        refresh with HTML export and podcast, Ollama cut off halfway, and a second refresh
    Your real data folder (%LOCALAPPDATA%\AgentReachDaily) is only read, never changed.
    Takes about 20-30 minutes. The result is a zip on your Desktop: send that file back.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Test-AgentReachDaily.ps1
    powershell -ExecutionPolicy Bypass -File .\Test-AgentReachDaily.ps1 -Quick
    powershell -ExecutionPolicy Bypass -File .\Test-AgentReachDaily.ps1 -Interactive
#>
[CmdletBinding()]
param(
    [switch]$Quick,          # skip the second real refresh
    [switch]$Interactive,    # also the steps where you quit Ollama by hand
    [switch]$SkipTests,      # skip the offline test suite
    [switch]$NoPause
)

# Windows PowerShell 5.1 can turn native stderr into terminating errors under "Stop";
# every native call below checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

function Wait-IfInteractive {
    if (-not $NoPause -and [Environment]::UserInteractive -and $Host.Name -eq "ConsoleHost") {
        Write-Host ""
        Read-Host "Press Enter to close" | Out-Null
    }
}

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Agent Reach Daily is not set up in $Root yet. Run this first:" -ForegroundColor Red
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1"
    Wait-IfInteractive
    exit 1
}

$selfTestArgs = @("-m", "tests.daily_selftest")
if ($SkipTests) {
    $selfTestArgs += "--skip-pytest"
} else {
    Write-Host "Installing the test tools (pytest, pyflakes) into .venv ..." -ForegroundColor Cyan
    & $VenvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $Root "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Could not install the test tools; the offline test suite is skipped." -ForegroundColor Yellow
        $selfTestArgs += "--skip-pytest"
    }
}
if ($Quick) { $selfTestArgs += "--quick" }
if ($Interactive) { $selfTestArgs += "--interactive" }
$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop) { $selfTestArgs += @("--out", $desktop) }

$env:PYTHONIOENCODING = "utf-8"
Push-Location -LiteralPath $Root
& $VenvPython @selfTestArgs
$code = $LASTEXITCODE
Pop-Location

$zip = $null
if ($desktop) {
    $zip = Get-ChildItem -LiteralPath $desktop -Filter "AgentReach-selftest-*.zip" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
Write-Host ""
if ($zip) {
    Write-Host "Send this file back: $($zip.FullName)" -ForegroundColor Green
    Start-Process explorer.exe -ArgumentList "/select,`"$($zip.FullName)`""
} else {
    Write-Host "No result zip was found on the Desktop; see the messages above." -ForegroundColor Yellow
}
Wait-IfInteractive
exit $code
