<#
.SYNOPSIS
    Compares the embedding models for story grouping on this PC, then runs the Daily self-test.

.DESCRIPTION
    1. Checks Ollama and the models to compare (default: nomic-embed-text, the first EmbeddingGemma
       (embeddinggemma:300m, runs on Windows), embeddinggemma-2:270m and the full EmbeddingGemma 2 model, tag
       embeddinggemma-2; Ollama runs EmbeddingGemma 2 on Macs only so far). Missing models are only downloaded
       with -PullModels; otherwise, or when a download fails, the benchmark lists them as "not available".
    2. Runs tests\embedding_benchmark.py on the labelled October 7 editions with every model: rc11-style
       grouping, the new same-event check, cosine ranges, cache reuse and timings. Nothing in your data
       folder is read or changed.
    3. Runs Test-AgentReachDaily.ps1 (the full self-test with real refreshes) unless -SkipSelfTest.
    Each model's download result is in pull-log.txt, and each model's vectors are saved so the comparison can
    be repeated offline. The results are two files on your Desktop: AgentReach-embedding-benchmark-<time>.zip and
    AgentReach-selftest-<time>.zip. Send both back.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Benchmark-Embeddings.ps1 -PullModels
    powershell -ExecutionPolicy Bypass -File .\Benchmark-Embeddings.ps1 -Models "embeddinggemma-2:270m,embeddinggemma-2" -SkipSelfTest
#>
[CmdletBinding()]
param(
    [string]$Models = "nomic-embed-text,embeddinggemma:300m,embeddinggemma-2:270m,embeddinggemma-2",
    [switch]$PullModels,
    [switch]$SkipSelfTest,
    [switch]$NoPause,
    [string]$OllamaHost = "http://localhost:11434"
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

$ollamaExe = $null
$cmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($cmd) { $ollamaExe = $cmd.Source }
elseif ($env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"))) {
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
}

$names = @()
try {
    $tags = Invoke-RestMethod -Uri "$OllamaHost/api/tags" -TimeoutSec 5 -ErrorAction Stop
    $names = @($tags.models | ForEach-Object { $_.name })
    Write-Host "Ollama is running at $OllamaHost" -ForegroundColor Green
} catch {
    Write-Host "Ollama is not answering at $OllamaHost. Start the Ollama app, then run this again." -ForegroundColor Red
    Wait-IfInteractive
    exit 1
}

$ollamaVersion = "version unknown"
try { $ollamaVersion = "version " + (Invoke-RestMethod -Uri "$OllamaHost/api/version" -TimeoutSec 5 -ErrorAction Stop).version }
catch { $ollamaVersion = "version unknown" }
Write-Host "Ollama $ollamaVersion"

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop) { $desktop = $Root }
$outDir = Join-Path $env:TEMP "AgentReach-embedding-benchmark-$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$pullLog = Join-Path $outDir "pull-log.txt"
"Ollama $ollamaVersion at $OllamaHost" | Out-File -FilePath $pullLog -Encoding utf8

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

$wanted = @($Models.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($m in $wanted) {
    $present = ($names -contains $m) -or ($names -contains "$($m):latest")
    if ($present) {
        Write-Host "Model $m is available" -ForegroundColor Green
        "$($m): already installed" | Out-File -FilePath $pullLog -Encoding utf8 -Append
        continue
    }
    if ($PullModels -and $ollamaExe) {
        Write-Host "Downloading model $m ..." -ForegroundColor Cyan
        & $ollamaExe pull $m
        $pullCode = $LASTEXITCODE
        if ($pullCode -eq 0) { "$($m): downloaded" | Out-File -FilePath $pullLog -Encoding utf8 -Append; continue }
        $why = Get-PullError $m
        if ($null -eq $why) {
            Write-Host "Model $m downloaded (second try)" -ForegroundColor Green
            "$($m): downloaded on the second try" | Out-File -FilePath $pullLog -Encoding utf8 -Append
            continue
        }
        "$($m): download failed (exit $pullCode): $why" | Out-File -FilePath $pullLog -Encoding utf8 -Append
        Write-Host "Downloading $m failed: $why" -ForegroundColor Yellow
        if ($m -like "embeddinggemma-2*" -and $why -match "MLX") {
            # Oct 7 on Windows, newest Ollama: "this model requires MLX support, but the MLX runtime is not available"
            Write-Host "Ollama can run $m only on Mac computers so far (it needs Apple's MLX); updating Ollama does not help yet." -ForegroundColor Yellow
        }
        elseif ($m -like "embeddinggemma*") {
            Write-Host "EmbeddingGemma 2 is new (October 2026) and may need a newer Ollama than this one ($ollamaVersion). Update Ollama from https://ollama.com/download (or choose 'Restart to update' in the Ollama tray menu), then run this again. Until then the app groups stories with nomic-embed-text." -ForegroundColor Yellow
        }
        Write-Host "The comparison continues; $m is reported as not available." -ForegroundColor Yellow
    } else {
        Write-Host "Model $m is missing (re-run with -PullModels, or: ollama pull $m)." -ForegroundColor Yellow
        "$($m): missing, not downloaded (no -PullModels)" | Out-File -FilePath $pullLog -Encoding utf8 -Append
    }
}

Write-Host ""
Write-Host "Comparing embedding models on the labelled October 7 editions ..." -ForegroundColor Cyan
$env:PYTHONIOENCODING = "utf-8"
Push-Location -LiteralPath $Root
# error lines become plain text (not PowerShell error records), and the file is written as UTF-8
# (Tee-Object writes UTF-16 in Windows PowerShell 5.1)
$benchLines = New-Object System.Collections.Generic.List[string]
& $VenvPython -m tests.embedding_benchmark --ollama --models ($wanted -join ",") --host $OllamaHost --out $outDir 2>&1 |
    ForEach-Object { $line = "$_"; $benchLines.Add($line); Write-Host $line }
$benchCode = $LASTEXITCODE
$benchLines | Out-File -FilePath (Join-Path $outDir "benchmark-output.txt") -Encoding utf8
& $VenvPython -c "import platform, sys; print(platform.platform(), sys.version)" 2>&1 |
    Out-File -FilePath (Join-Path $outDir "machine.txt") -Encoding utf8
"Ollama $ollamaVersion" | Out-File -FilePath (Join-Path $outDir "machine.txt") -Encoding utf8 -Append
if ($ollamaExe) { & $ollamaExe list 2>&1 | Out-File -FilePath (Join-Path $outDir "ollama-list.txt") -Encoding utf8 }
Pop-Location

$zip = Join-Path $desktop "AgentReach-embedding-benchmark-$stamp.zip"
Compress-Archive -Path (Join-Path $outDir "*") -DestinationPath $zip -Force
if ($benchCode -ne 0) {
    Write-Host "The benchmark stopped with an error (exit $benchCode); the zip has its output." -ForegroundColor Yellow
} else {
    Write-Host "Benchmark result: $zip" -ForegroundColor Green
}

if (-not $SkipSelfTest) {
    Write-Host ""
    Write-Host "Running the Daily self-test (real refreshes, about 20-30 minutes) ..." -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "Test-AgentReachDaily.ps1") -NoPause
}

Write-Host ""
Write-Host "Send back the files on your Desktop: AgentReach-embedding-benchmark-$stamp.zip" -ForegroundColor Green
if (-not $SkipSelfTest) { Write-Host "and the newest AgentReach-selftest-*.zip" -ForegroundColor Green }
Wait-IfInteractive
exit $benchCode
