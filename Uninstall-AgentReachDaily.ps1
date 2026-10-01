<#
.SYNOPSIS
    Removes the Agent Reach Daily scheduled task and shortcuts. Your news history is KEPT by default.

.DESCRIPTION
    Always (unless -DryRun):
      - deletes the current-user scheduled task "AgentReachDaily-Refresh" if it exists.
    By default:
      - deletes the "Agent Reach" Desktop and Start-menu shortcuts that point into this folder
        (keep them with -KeepShortcuts).
    Only when asked:
      - -RemoveVenv       deletes this folder's .venv (the project's Python environment).
      - -DeleteUserData   deletes %LOCALAPPDATA%\AgentReachDaily: every edition, your settings, logs and
                          trend history. You must type DELETE to confirm (or pass -Force).
    The source code in this folder is never deleted.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Uninstall-AgentReachDaily.ps1
    powershell -ExecutionPolicy Bypass -File .\Uninstall-AgentReachDaily.ps1 -DryRun
    powershell -ExecutionPolicy Bypass -File .\Uninstall-AgentReachDaily.ps1 -RemoveVenv -DeleteUserData
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$KeepShortcuts,
    [switch]$RemoveVenv,
    [switch]$DeleteUserData,
    [switch]$Force,
    [switch]$NoPause
)

$ErrorActionPreference = "Continue"
$TaskName = "AgentReachDaily-Refresh"

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "    OK   $msg" -ForegroundColor Green }
function Write-Note([string]$msg) { Write-Host "    ..   $msg" }
function Write-Warn2([string]$msg) { Write-Host "    WARN $msg" -ForegroundColor Yellow }
function Write-Dry([string]$msg) { Write-Host "    [dry run] would $msg" -ForegroundColor Magenta }
function Wait-IfInteractive {
    if (-not $NoPause -and [Environment]::UserInteractive -and $Host.Name -eq "ConsoleHost") {
        Write-Host ""
        Read-Host "Press Enter to close" | Out-Null
    }
}

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$DataDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "AgentReachDaily" } else { $null }

Write-Host "Agent Reach Daily uninstall" -ForegroundColor White
if ($DryRun) { Write-Host "DRY RUN: nothing will be removed." -ForegroundColor Magenta }

# ------------------------------------------------------------------ 1. scheduled task
Write-Step "Scheduled task"
$schtasks = Get-Command schtasks.exe -ErrorAction SilentlyContinue
if (-not $schtasks) { Write-Note "Task Scheduler is not available on this system." }
else {
    & schtasks.exe /Query /TN $TaskName 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Ok "No scheduled task named $TaskName (nothing to remove)" }
    elseif ($DryRun) { Write-Dry "delete the scheduled task $TaskName" }
    else {
        & schtasks.exe /Delete /TN $TaskName /F | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Ok "Deleted scheduled task $TaskName" }
        else { Write-Warn2 "Could not delete $TaskName. Remove it in Task Scheduler (Task Scheduler Library)." }
    }
}

# ------------------------------------------------------------------ 2. shortcuts
Write-Step "Shortcuts"
if ($KeepShortcuts) { Write-Note "Kept (-KeepShortcuts)" }
else {
    $paths = @()
    foreach ($folder in @("Desktop", "Programs")) {
        $dir = [Environment]::GetFolderPath($folder)
        if ($dir) { $paths += (Join-Path $dir "Agent Reach.lnk") }
    }
    $shell = $null
    try { $shell = New-Object -ComObject WScript.Shell } catch { $shell = $null }
    foreach ($p in $paths) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $ours = $true
        if ($shell) {
            $target = $shell.CreateShortcut($p).TargetPath
            $ours = ($target -and $target.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase))
        }
        if (-not $ours) { Write-Note "Kept $p (it points somewhere else)"; continue }
        if ($DryRun) { Write-Dry "delete $p" }
        else {
            Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $p) { Write-Warn2 "Could not delete $p" } else { Write-Ok "Deleted $p" }
        }
    }
}

# ------------------------------------------------------------------ 3. project environment
Write-Step "Project environment (.venv)"
$venv = Join-Path $Root ".venv"
if (-not $RemoveVenv) { Write-Note "Kept $venv (remove it with -RemoveVenv)" }
elseif (-not (Test-Path -LiteralPath $venv)) { Write-Ok "No .venv folder" }
elseif ($DryRun) { Write-Dry "delete $venv" }
else {
    Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $venv) { Write-Warn2 "Could not fully delete $venv (close Agent Reach and try again)." }
    else { Write-Ok "Deleted $venv" }
}

# ------------------------------------------------------------------ 4. personal data
Write-Step "Your editions, settings, logs and history"
if (-not $DataDir -or -not (Test-Path -LiteralPath $DataDir)) { Write-Ok "No data folder found" }
elseif (-not $DeleteUserData) {
    Write-Ok "KEPT: $DataDir"
    Write-Note "Re-installing later picks this up again. To erase it, run with -DeleteUserData."
} else {
    $lockInfo = Join-Path $DataDir "state\refresh.lock.json"
    if (Test-Path -LiteralPath $lockInfo) { Write-Warn2 "A refresh may be running. Close Agent Reach first if deletion fails." }
    $confirmed = $Force
    if (-not $confirmed -and -not $DryRun) {
        Write-Host "    This permanently deletes every saved edition, your settings, logs and trend history in:" -ForegroundColor Yellow
        Write-Host "    $DataDir" -ForegroundColor Yellow
        $answer = Read-Host "    Type DELETE to confirm"
        $confirmed = ($answer -ceq "DELETE")
    }
    if ($DryRun) { Write-Dry "delete $DataDir (after you type DELETE)" }
    elseif (-not $confirmed) { Write-Ok "Not confirmed: KEPT $DataDir" }
    else {
        Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $DataDir) { Write-Warn2 "Some files could not be deleted (close Agent Reach and try again)." }
        else { Write-Ok "Deleted $DataDir" }
    }
}

Write-Host ""
if ($DryRun) { Write-Host "Dry run finished. Nothing was changed." -ForegroundColor Magenta }
else { Write-Host "Done. The Agent Reach source folder itself was not touched: $Root" -ForegroundColor Green }
Wait-IfInteractive
exit 0
