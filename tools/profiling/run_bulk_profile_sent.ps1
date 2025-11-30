Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath "..") -ChildPath "..")
Set-Location $repoRoot

$sourcePath = 'C:\Users\v_ale\My Drive (zarnica@gmail.com)\resume\sent'

& (Join-Path $PSScriptRoot "run_bulk_profile.ps1") -SourcePath $sourcePath -JsonOutput "tools/profiling/bulk_profile_sent.json"
