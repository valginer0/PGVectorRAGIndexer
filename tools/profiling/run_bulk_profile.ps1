param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,

    [string]$BaseUrl = "http://localhost:8000",

    [string]$JsonOutput = "tools/profiling/bulk_profile.json",

    [switch]$ForceReindex,

    [string]$DocumentType,

    [double]$TimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Convert-ToWslPath {
    param([string]$WindowsPath)
    $resolved = [System.IO.Path]::GetFullPath($WindowsPath)
    $escaped = $resolved -replace "'", "'""'""'"
    $wslPath = & wsl.exe -d Ubuntu -e bash -lc "wslpath -a '$escaped'"
    if (-not $wslPath) {
        throw "Failed to convert path to WSL format: $WindowsPath"
    }
    return $wslPath
}

function Escape-SingleQuotes {
    param([string]$Value)
    return $Value -replace "'", "'""'""'"
}

$repoRoot = Resolve-Path (Split-Path -Path (Split-Path -Path $PSScriptRoot -Parent) -Parent)
Set-Location $repoRoot

$wslRepo = "/home/valginer0/projects/PGVectorRAGIndexer"
$wslSource = Convert-ToWslPath -WindowsPath $SourcePath
if ([System.IO.Path]::IsPathRooted($JsonOutput)) {
    $jsonFullPath = [System.IO.Path]::GetFullPath($JsonOutput)
    $jsonDir = Split-Path -Path $jsonFullPath -Parent
    if (-not (Test-Path $jsonDir)) {
        New-Item -ItemType Directory -Path $jsonDir -Force | Out-Null
    }
    $wslJson = Convert-ToWslPath -WindowsPath $jsonFullPath
}
else {
    $jsonFullPath = Join-Path $repoRoot $JsonOutput
    $jsonDir = Split-Path -Path $jsonFullPath -Parent
    if (-not (Test-Path $jsonDir)) {
        New-Item -ItemType Directory -Path $jsonDir -Force | Out-Null
    }
    $relativeJson = ($JsonOutput -replace "\\", "/").TrimStart("/")
    $wslJson = "{0}/{1}" -f $wslRepo.TrimEnd('/'), $relativeJson
}

$escapedSource = Escape-SingleQuotes $wslSource
$escapedJson = Escape-SingleQuotes $wslJson
$escapedBaseUrl = Escape-SingleQuotes $BaseUrl

$command = @(
    "cd $wslRepo",
    "source venv/bin/activate",
    "python tools/profiling/profile_bulk_upload.py '$escapedSource' --base-url '$escapedBaseUrl' --timeout $TimeoutSeconds --json '$escapedJson'"
)

if ($ForceReindex) {
    $command[2] += " --force-reindex"
}

if ($DocumentType) {
    $escapedDocType = Escape-SingleQuotes $DocumentType
    $command[2] += " --document-type '$escapedDocType'"
}

$bash = [string]::Join(" ; ", $command)

Write-Host "Running bulk profile via WSL..." -ForegroundColor Cyan
Write-Host "Source (Windows): $SourcePath" -ForegroundColor Gray
Write-Host "Source (WSL): $wslSource" -ForegroundColor Gray
Write-Host "Output (JSON): $JsonOutput" -ForegroundColor Gray

& wsl.exe -d Ubuntu -e bash -lc $bash
