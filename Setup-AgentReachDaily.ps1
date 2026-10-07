<#
.SYNOPSIS
    One-time setup for Agent Reach Daily on Windows (current user, no administrator rights).

.DESCRIPTION
    1. Finds Python 3.10+ with tkinter (the py launcher or python on PATH).
    2. Creates or reuses the project environment .venv in this folder and installs requirements.txt.
    3. Checks the Daily app imports and its command line.
    4. Checks Ollama and the local models (llama3.1:8b; embeddinggemma-2:270m groups the stories,
       nomic-embed-text is its fallback).
       Missing models are only downloaded with -PullModels (several GB; you are told first).
    5. Creates the data folder %LOCALAPPDATA%\AgentReachDaily with default settings.
    6. Creates "Agent Reach" shortcuts on the Desktop and in the Start menu (skip with -NoShortcut).
    7. Registers the hourly "is a refresh due?" scheduled task only with -RegisterTask.

    Nothing is deleted. Re-running the script is safe: it reuses what is already there.
    Use -DryRun to see every step without changing anything.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1
    powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -RegisterTask -PullModels
    powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$RegisterTask,
    [switch]$PullModels,
    [switch]$NoShortcut,
    [string]$Python = "",
    [string]$OllamaHost = "http://localhost:11434",
    [switch]$NoPause
)

# Windows PowerShell 5.1 can turn native stderr into terminating errors under "Stop";
# every native call below checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

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
function Fail([string]$msg) {
    Write-Host ""
    Write-Host "SETUP STOPPED: $msg" -ForegroundColor Red
    Wait-IfInteractive
    exit 1
}

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvPythonW = Join-Path $Venv "Scripts\pythonw.exe"
$Requirements = Join-Path $Root "requirements.txt"
$warnings = New-Object System.Collections.Generic.List[string]

Write-Host "Agent Reach Daily setup" -ForegroundColor White
Write-Host "Project folder: $Root"
if ($DryRun) { Write-Host "DRY RUN: nothing will be created, installed, registered or downloaded." -ForegroundColor Magenta }

# ------------------------------------------------------------------ 1. project
Write-Step "Checking the project folder"
if (-not (Test-Path -LiteralPath (Join-Path $Root "agent_reach\daily\__main__.py"))) {
    Fail "agent_reach\daily was not found next to this script. Run the script from the Agent Reach folder."
}
if (-not (Test-Path -LiteralPath $Requirements)) { Fail "requirements.txt is missing in $Root." }
Write-Ok "Agent Reach source found"

# ------------------------------------------------------------------ 2. python
Write-Step "Finding Python 3.10 or newer (with tkinter)"
function Test-PythonCandidate([string[]]$cmd) {
    $exe = $cmd[0]
    $rest = @()
    if ($cmd.Count -gt 1) { $rest = $cmd[1..($cmd.Count - 1)] }
    $probe = "import sys, tkinter; print(sys.executable); print('%d.%d' % sys.version_info[:2])"
    $out = & $exe @rest -c $probe 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
    $lines = @($out)
    if ($lines.Count -lt 2) { return $null }
    $ver = [version]($lines[1].Trim())
    if ($ver -lt [version]"3.10") { return $null }
    return @{ Path = $lines[0].Trim(); Version = $lines[1].Trim() }
}

$basePython = $null
$candidates = @()
if ($Python) { $candidates += , @($Python) }
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("3.13", "3.12", "3.11", "3.10")) { $candidates += , @("py", "-$v") }
}
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += , @("python") }
foreach ($c in $candidates) {
    $found = Test-PythonCandidate $c
    if ($found) { $basePython = $found; break }
}
if (Test-Path -LiteralPath $VenvPython) {
    $venvInfo = Test-PythonCandidate @($VenvPython)
    if ($venvInfo) { Write-Ok "Existing environment .venv uses Python $($venvInfo.Version)" }
    else { Write-Warn2 "The existing .venv does not work (Python too old, broken, or no tkinter)." }
}
if (-not $basePython -and -not (Test-Path -LiteralPath $VenvPython)) {
    Fail ("No suitable Python found. Install Python 3.12 from https://www.python.org/downloads/windows/ " +
          "(tick 'tcl/tk and IDLE' and 'py launcher'), then run this script again.")
}
if ($basePython) { Write-Ok "Python $($basePython.Version) at $($basePython.Path)" }

# ------------------------------------------------------------------ 3. venv + packages
Write-Step "Preparing the project environment (.venv)"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    if ($DryRun) { Write-Dry "create $Venv with $($basePython.Path)" }
    else {
        & $basePython.Path -m venv $Venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) { Fail "Could not create $Venv." }
        Write-Ok "Created $Venv"
    }
} else {
    Write-Ok "Reusing $Venv"
}

$hashFile = Join-Path $Venv ".agent-reach-requirements.sha256"
$reqHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$installed = $false
if ((Test-Path -LiteralPath $hashFile) -and ((Get-Content -LiteralPath $hashFile -Raw).Trim() -eq $reqHash)) {
    Write-Ok "Requirements already installed (requirements.txt unchanged)"
    $installed = $true
}
if (-not $installed) {
    if ($DryRun) { Write-Dry "run: .venv\Scripts\python.exe -m pip install -r requirements.txt" }
    else {
        Write-Note "Installing requirements (first time: a few minutes)..."
        & $VenvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
        & $VenvPython -m pip install --disable-pip-version-check --quiet -r $Requirements
        if ($LASTEXITCODE -ne 0) { Fail "pip could not install requirements.txt (see the messages above; check your internet connection)." }
        Set-Content -LiteralPath $hashFile -Value $reqHash -Encoding ASCII
        Write-Ok "Requirements installed"
    }
}

# The project folder on the environment's import path, so "python -m agent_reach.daily" also works
# when started from another folder (a shortcut, Task Scheduler or a terminal elsewhere).
if ((Test-Path -LiteralPath $VenvPython) -and -not $DryRun) {
    $sitePackages = & $VenvPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $sitePackages) {
        $pth = Join-Path ($sitePackages | Select-Object -First 1).Trim() "agent_reach_project.pth"
        [IO.File]::WriteAllText($pth, $Root + "`r`n", (New-Object System.Text.UTF8Encoding $false))
        Write-Ok "Agent Reach can be started from any folder (project path registered in .venv)"
    } else {
        Write-Warn2 "Could not find the environment's site-packages; start the app from this folder or its shortcuts."
    }
} elseif ($DryRun) {
    Write-Dry "register $Root in .venv (agent_reach_project.pth) so the app starts from any folder"
}

# ------------------------------------------------------------------ 4. validate the app
Write-Step "Checking Agent Reach Daily"
$haveVenv = Test-Path -LiteralPath $VenvPython
if ($haveVenv) {
    Push-Location -LiteralPath $Root
    & $VenvPython -c "import tzdata, agent_reach.daily.gui, agent_reach.daily.refresh" 2>$null
    $importOk = ($LASTEXITCODE -eq 0)
    $version = & $VenvPython -m agent_reach.daily --version 2>$null
    $cliOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $importOk) {
        if ($DryRun) { Write-Warn2 "The app does not import yet (packages not installed: expected before the first real run)." }
        else { Fail "The app does not import. Run: .venv\Scripts\python.exe -m pip install -r requirements.txt" }
    } elseif (-not $cliOk) { Fail "python -m agent_reach.daily --version failed." }
    else { Write-Ok "$version" }
} else {
    Write-Dry "check: python -m agent_reach.daily --version"
}

# ------------------------------------------------------------------ 5. ollama + models
Write-Step "Checking Ollama (local AI) and the models"
$ollamaExe = $null
$cmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($cmd) { $ollamaExe = $cmd.Source }
elseif ($env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"))) {
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
}
if ($ollamaExe) { Write-Ok "Ollama installed: $ollamaExe" }
else {
    Write-Warn2 "Ollama is not installed. Download it from https://ollama.com/download, then run this script again."
    $warnings.Add("Install Ollama from https://ollama.com/download")
}

$models = @("llama3.1:8b", "embeddinggemma-2:270m", "nomic-embed-text")
$names = @()
$reachable = $false
try {
    $tags = Invoke-RestMethod -Uri "$OllamaHost/api/tags" -TimeoutSec 5 -ErrorAction Stop
    $reachable = $true
    $names = @($tags.models | ForEach-Object { $_.name })
    Write-Ok "Ollama is running at $OllamaHost"
} catch {
    Write-Warn2 "Ollama is not answering at $OllamaHost. Start the Ollama app (Start menu > Ollama)."
    $warnings.Add("Start Ollama before refreshing (the app also tries to start it automatically)")
}
$ollamaVersion = "version unknown"
if ($reachable) {
    try { $ollamaVersion = "version " + (Invoke-RestMethod -Uri "$OllamaHost/api/version" -TimeoutSec 5 -ErrorAction Stop).version }
    catch { $ollamaVersion = "version unknown" }
    Write-Ok "Ollama $ollamaVersion"
}

function Get-PullError([string]$model) {
    # Ask the Ollama server itself why: its answer names the reason ('ollama pull' prints it only on screen).
    # Returns $null when this second try downloads the model after all.
    try {
        $body = @{ model = $model; stream = $false } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Uri "$OllamaHost/api/pull" -Body $body -ContentType "application/json" -TimeoutSec 600 -ErrorAction Stop | Out-Null
        return $null
    } catch {
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $msg = $_.ErrorDetails.Message
            try { $j = $msg | ConvertFrom-Json -ErrorAction Stop; if ($j.error) { return [string]$j.error } } catch { }
            return $msg
        }
        return $_.Exception.Message
    }
}

function Test-ModelPresent([string]$wanted, [string[]]$have) {
    if ($have -contains $wanted -or $have -contains "$($wanted):latest") { return $true }
    if ($wanted -notmatch ":") { foreach ($n in $have) { if ($n.Split(":")[0] -eq $wanted) { return $true } } }
    return $false
}

if ($reachable) {
    foreach ($m in $models) {
        if (Test-ModelPresent $m $names) { Write-Ok "Model $m is available"; continue }
        $size = if ($m -like "llama3.1*") { "about 4.9 GB" } elseif ($m -like "embeddinggemma*") { "a few hundred MB" } else { "about 274 MB" }
        if ($PullModels -and $ollamaExe) {
            if ($DryRun) { Write-Dry "download model $m ($size): ollama pull $m" }
            else {
                Write-Note "Downloading model $m ($size). This can take a while..."
                & $ollamaExe pull $m
                if ($LASTEXITCODE -eq 0) { Write-Ok "Model $m downloaded" }
                else {
                    $why = Get-PullError $m
                    if ($null -eq $why) { Write-Ok "Model $m downloaded (second try)" }
                    elseif ($m -like "embeddinggemma*") {
                        Write-Warn2 "Downloading $m failed: $why"
                        Write-Warn2 "EmbeddingGemma 2 is new (October 2026) and may need a newer Ollama than this one ($ollamaVersion). Update Ollama from https://ollama.com/download (or choose 'Restart to update' in the Ollama tray menu), then run this again. Until then the app groups stories with nomic-embed-text."
                        $warnings.Add("Optional (better story grouping): update Ollama, then run: ollama pull $m")
                    } else {
                        Write-Warn2 "Downloading $m failed: $why"
                        $warnings.Add("Run: ollama pull $m")
                    }
                }
            }
        } else {
            Write-Warn2 "Model $m is missing ($size). Download it with:  ollama pull $m   (or re-run with -PullModels)"
            $warnings.Add("Run: ollama pull $m")
        }
    }
}

# ------------------------------------------------------------------ 6. data folder
Write-Step "Preparing your data folder"
$dataDir = Join-Path $env:LOCALAPPDATA "AgentReachDaily"
if ($DryRun -or -not $haveVenv) { Write-Dry "create $dataDir with default settings (existing files are kept)" }
else {
    Push-Location -LiteralPath $Root
    & $VenvPython -m agent_reach.daily --init | Out-Null
    $initOk = ($LASTEXITCODE -eq 0)
    Pop-Location
    if ($initOk) { Write-Ok "Data folder: $dataDir (editions, settings, logs; existing files kept)" }
    else { Fail "Could not create the data folder $dataDir." }
}

# ------------------------------------------------------------------ 7. shortcuts
Write-Step "Shortcuts"
$shortcutTargets = @()
foreach ($folder in @("Desktop", "Programs")) {
    $dir = [Environment]::GetFolderPath($folder)
    if ($dir) { $shortcutTargets += (Join-Path $dir "Agent Reach.lnk") }
}
if ($NoShortcut) { Write-Note "Skipped (-NoShortcut)" }
else {
    foreach ($lnkPath in $shortcutTargets) {
        if ($DryRun) { Write-Dry "create shortcut $lnkPath -> .venv\Scripts\pythonw.exe -m agent_reach.daily --gui"; continue }
        try {
            $shell = New-Object -ComObject WScript.Shell
            $lnk = $shell.CreateShortcut($lnkPath)
            $lnk.TargetPath = $VenvPythonW
            $lnk.Arguments = "-m agent_reach.daily --gui"
            $lnk.WorkingDirectory = $Root
            $lnk.Description = "Agent Reach Daily - your local daily news briefing"
            $lnk.Save()
            Write-Ok "Created $lnkPath"
        } catch {
            Write-Warn2 "Could not create $lnkPath ($($_.Exception.Message))"
        }
    }
}

# ------------------------------------------------------------------ 8. scheduled task
Write-Step "Background refresh (Windows Task Scheduler)"
if ($RegisterTask) {
    if (-not $haveVenv) { Write-Dry "register the scheduled task AgentReachDaily-Refresh" }
    else {
        Push-Location -LiteralPath $Root
        if ($DryRun) {
            & $VenvPython -m agent_reach.daily --install-task --dry-run | Select-Object -First 1
        } else {
            & $VenvPython -m agent_reach.daily --install-task
            if ($LASTEXITCODE -ne 0) { $warnings.Add("The scheduled task could not be registered (see above); the app still refreshes while it is open") }
            else { Write-Ok "Task AgentReachDaily-Refresh registered: checks hourly and at logon, refreshes only when due" }
        }
        Pop-Location
    }
} else {
    Write-Note "Not registered. To refresh in the background while you are logged on, run this script with -RegisterTask"
    Write-Note "(or use Settings > Schedule > Enable in the app). Without it, the app refreshes when you open it."
}

# ------------------------------------------------------------------ summary
Write-Host ""
if ($DryRun) { Write-Host "Dry run finished. Nothing was changed." -ForegroundColor Magenta }
else { Write-Host "Setup finished." -ForegroundColor Green }
if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "Still to do:" -ForegroundColor Yellow
    foreach ($w in $warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
}
Write-Host ""
Write-Host "Start Agent Reach Daily:" -ForegroundColor White
if (-not $NoShortcut) { Write-Host "  - double-click 'Agent Reach' on your Desktop or in the Start menu" }
Write-Host "  - or double-click AgentReachDaily.pyw (or AgentReachDaily.cmd) in $Root"
Write-Host "  - or from PowerShell in this folder:  .\.venv\Scripts\python.exe -m agent_reach.daily"
Write-Host ""
Write-Host "Refresh from the command line:  .\.venv\Scripts\python.exe -m agent_reach.daily --refresh-now"
Write-Host "Remove the scheduled task/shortcuts later:  powershell -ExecutionPolicy Bypass -File .\Uninstall-AgentReachDaily.ps1"
Wait-IfInteractive
exit 0
