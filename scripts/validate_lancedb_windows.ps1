<#
.SYNOPSIS
    Clean-room Windows validation for LanceDB + PySide6 + sentence-transformers packaging.

.DESCRIPTION
    Runs four sequential gates inside a fresh CPython venv (not Anaconda):
      Gate 1  Import check  torch, transformers, sentence_transformers, lancedb, PySide6
      Gate 2  Source run    lancedb_pyside6_prototype.py --headless
      Gate 3  PyInstaller   freeze prototype to .exe
      Gate 4  Frozen run    execute the frozen .exe --headless

    Results are written to docs/internal/LANCEDB_WINDOWS_VALIDATION_V1.md so they
    can be committed to the private docs branch.

.PARAMETER RepoRoot
    Absolute path to the PGVectorRAGIndexer repository checkout on Windows.
    Default: parent of this script's directory.

.PARAMETER ValidationDir
    Persistent folder for the clean venv and build artefacts.
    Default: C:\Users\<you>\.codex\validation\PGVectorRAGIndexer\clean-cpython-lancedb

.PARAMETER PythonExe
    Path to a python.org CPython executable. Must NOT be Anaconda/Miniconda.
    If omitted the script searches PATH for the first non-Anaconda Python 3.11+.

.EXAMPLE
    # Run everything with defaults
    .\scripts\validate_lancedb_windows.ps1

.EXAMPLE
    # Point at a specific CPython install
    .\scripts\validate_lancedb_windows.ps1 -PythonExe "C:\Python311\python.exe"
#>

param(
    [string]$RepoRoot      = (Split-Path $PSScriptRoot -Parent),
    [string]$ValidationDir = "$env:USERPROFILE\.codex\validation\PGVectorRAGIndexer\clean-cpython-lancedb",
    [string]$PythonExe     = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Gate { param([string]$Msg) Write-Host "`n=== $Msg ===" -ForegroundColor Cyan }
function Write-Pass { param([string]$Msg) Write-Host "[PASS] $Msg" -ForegroundColor Green }
function Write-Fail { param([string]$Msg) Write-Host "[FAIL] $Msg" -ForegroundColor Red }
function Write-Info { param([string]$Msg) Write-Host "       $Msg" -ForegroundColor Gray }

$Results   = [ordered]@{}
$StartTime = Get-Date

# ---------------------------------------------------------------------------
# Gate 0: Locate a non-Anaconda CPython 3.11+
# ---------------------------------------------------------------------------
Write-Gate "Gate 0: Locate CPython (non-Anaconda)"

function Find-CPython {
    $candidates = @()
    if ($PythonExe -ne "") { $candidates += $PythonExe }
    $candidates += (Get-Command python   -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    $candidates += (Get-Command python3  -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    $candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python312\python.exe"
    )

    foreach ($exe in $candidates) {
        if (-not $exe -or -not (Test-Path $exe)) { continue }
        $info = & $exe -c "import sys; print(sys.version); print(sys.executable)" 2>&1
        if ($LASTEXITCODE -ne 0) { continue }
        $exePath = (& $exe -c "import sys; print(sys.executable)" 2>&1).Trim()
        # Reject Anaconda / Miniconda / conda
        if ($exePath -match "anaconda|miniconda|conda" -or $exePath -match "\\envs\\") {
            Write-Info "Skipping Anaconda Python: $exePath"
            continue
        }
        $verLine = (& $exe -c "import sys; print(sys.version_info[:2])" 2>&1).Trim()
        if ($verLine -match "\(3, (1[1-9]|[2-9]\d)") {
            Write-Pass "Found CPython: $exePath"
            Write-Info "Version: $((& $exe --version 2>&1).Trim())"
            return $exe
        }
        Write-Info "Python too old at $exePath ($verLine)"
    }
    return $null
}

$Python = Find-CPython
if (-not $Python) {
    Write-Fail "No suitable CPython 3.11+ found. Install from https://python.org and re-run."
    Write-Fail "Do NOT use Anaconda or Miniconda."
    exit 1
}
$Results["python_exe"] = $Python

# ---------------------------------------------------------------------------
# Create / reuse clean venv
# ---------------------------------------------------------------------------
Write-Gate "Setup: Create clean venv"

$VenvDir    = Join-Path $ValidationDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvDir)) {
    New-Item -ItemType Directory -Path $ValidationDir -Force | Out-Null
    Write-Info "Creating venv at $VenvDir ..."
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "venv creation failed"; exit 1 }
    Write-Pass "Venv created"
} else {
    Write-Info "Reusing existing venv at $VenvDir"
    Write-Info "Delete $VenvDir manually to force a full reinstall"
}

# Upgrade pip silently
& $VenvPip install --upgrade pip --quiet

# ---------------------------------------------------------------------------
# Install dependencies
# ---------------------------------------------------------------------------
Write-Gate "Setup: Install packages"

$Packages = @(
    # CPU-only torch (avoids CUDA driver requirement and keeps binary smaller)
    @{ name="torch (CPU)";              args=@("install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu", "--quiet") },
    @{ name="transformers";             args=@("install", "transformers", "--quiet") },
    @{ name="sentence-transformers";    args=@("install", "sentence-transformers", "--quiet") },
    @{ name="lancedb";                  args=@("install", "lancedb", "--quiet") },
    @{ name="pyarrow";                  args=@("install", "pyarrow", "--quiet") },
    @{ name="PySide6";                  args=@("install", "PySide6", "--quiet") },
    @{ name="psutil";                   args=@("install", "psutil", "--quiet") },
    @{ name="pyinstaller";              args=@("install", "pyinstaller", "--quiet") }
)

foreach ($pkg in $Packages) {
    Write-Info "Installing $($pkg.name) ..."
    & $VenvPip @($pkg.args) 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Failed to install $($pkg.name)"
        $Results["install_$($pkg.name)"] = "FAIL"
    } else {
        Write-Pass "$($pkg.name) installed"
        $Results["install_$($pkg.name)"] = "PASS"
    }
}

# ---------------------------------------------------------------------------
# Gate 1: Import check
# ---------------------------------------------------------------------------
Write-Gate "Gate 1: Import check"

$ImportScript = @"
import sys
failed = []
for mod in ["torch", "transformers", "sentence_transformers", "lancedb", "pyarrow", "PySide6"]:
    try:
        __import__(mod)
    except Exception as e:
        failed.append(f"{mod}: {e}")
if failed:
    print("FAIL")
    for f in failed: print(f"  {f}")
    sys.exit(1)
else:
    print("PASS")
    sys.exit(0)
"@

$ImportResult = & $VenvPython -c $ImportScript 2>&1
$Gate1Pass = $LASTEXITCODE -eq 0
if ($Gate1Pass) {
    Write-Pass "All imports succeeded"
    $Results["gate1_imports"] = "PASS"
} else {
    Write-Fail "Import failures detected:"
    $ImportResult | ForEach-Object { Write-Info $_ }
    $Results["gate1_imports"] = "FAIL: $ImportResult"
}

# ---------------------------------------------------------------------------
# Gate 2: Source prototype headless run
# ---------------------------------------------------------------------------
Write-Gate "Gate 2: Source prototype headless run"

$ProtoScript = Join-Path $RepoRoot "scripts\lancedb_pyside6_prototype.py"
$ProtoLanceDir = Join-Path $ValidationDir "lancedb_data"

if ($Gate1Pass) {
    $ProtoOutput = & $VenvPython $ProtoScript `
        --headless `
        --search "EV6 battery troubleshooting" `
        --lance-path $ProtoLanceDir 2>&1
    $Gate2Pass = $LASTEXITCODE -eq 0
    if ($Gate2Pass) {
        Write-Pass "Headless run exited cleanly"
        $Results["gate2_source_run"] = "PASS"
    } else {
        Write-Fail "Headless run failed:"
        $ProtoOutput | Select-Object -Last 20 | ForEach-Object { Write-Info $_ }
        $Results["gate2_source_run"] = "FAIL"
    }
} else {
    Write-Info "Skipped (Gate 1 failed)"
    $Results["gate2_source_run"] = "SKIPPED"
    $Gate2Pass = $false
}

# ---------------------------------------------------------------------------
# Gate 3: PyInstaller freeze
# ---------------------------------------------------------------------------
Write-Gate "Gate 3: PyInstaller freeze"

$DistDir  = Join-Path $ValidationDir "dist"
$BuildDir = Join-Path $ValidationDir "build"
$FrozenExe = Join-Path $DistDir "lancedb_pyside6_prototype.exe"

if ($Gate2Pass) {
    Write-Info "Building frozen exe (this may take several minutes) ..."
    $PyiArgs = @(
        $ProtoScript,
        "--onefile",
        "--distpath", $DistDir,
        "--workpath", $BuildDir,
        "--specpath", $ValidationDir,
        "--collect-all", "lancedb",
        "--collect-all", "pyarrow",
        "--collect-all", "sentence_transformers",
        "--collect-all", "transformers",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtGui",
        "--noconfirm",
        "--clean"
    )
    $PyiOutput = & $VenvPython -m PyInstaller @($PyiArgs) 2>&1
    $Gate3Pass = $LASTEXITCODE -eq 0 -and (Test-Path $FrozenExe)
    if ($Gate3Pass) {
        $ExeSize = [math]::Round((Get-Item $FrozenExe).Length / 1MB, 1)
        Write-Pass "Frozen exe built: $FrozenExe ($ExeSize MB)"
        $Results["gate3_pyinstaller"] = "PASS ($ExeSize MB)"
    } else {
        Write-Fail "PyInstaller failed or exe not produced"
        $PyiOutput | Select-Object -Last 30 | ForEach-Object { Write-Info $_ }
        $Results["gate3_pyinstaller"] = "FAIL"
    }
} else {
    Write-Info "Skipped (Gate 2 failed)"
    $Results["gate3_pyinstaller"] = "SKIPPED"
    $Gate3Pass = $false
}

# ---------------------------------------------------------------------------
# Gate 4: Frozen exe headless run
# ---------------------------------------------------------------------------
Write-Gate "Gate 4: Frozen exe headless run"

if ($Gate3Pass) {
    $FrozenLanceDir = Join-Path $ValidationDir "lancedb_data_frozen"
    $FrozenOutput = & $FrozenExe `
        --headless `
        --search "EV6 battery troubleshooting" `
        --lance-path $FrozenLanceDir 2>&1
    $Gate4Pass = $LASTEXITCODE -eq 0
    if ($Gate4Pass) {
        Write-Pass "Frozen exe ran headlessly and exited cleanly"
        $Results["gate4_frozen_run"] = "PASS"
    } else {
        Write-Fail "Frozen exe failed:"
        $FrozenOutput | Select-Object -Last 20 | ForEach-Object { Write-Info $_ }
        $Results["gate4_frozen_run"] = "FAIL: $($FrozenOutput | Select-Object -Last 5)"
    }
} else {
    Write-Info "Skipped (Gate 3 failed)"
    $Results["gate4_frozen_run"] = "SKIPPED"
    $Gate4Pass = $false
}

# ---------------------------------------------------------------------------
# Write result document to docs/internal
# ---------------------------------------------------------------------------
Write-Gate "Writing result document"

$DocsInternal = Join-Path $RepoRoot "docs\internal"
$ResultFile   = Join-Path $DocsInternal "LANCEDB_WINDOWS_VALIDATION_V1.md"
$RunDate      = (Get-Date).ToString("yyyy-MM-dd")
$Duration     = [math]::Round(((Get-Date) - $StartTime).TotalMinutes, 1)
$Overall      = if ($Gate4Pass) { "PASS" } elseif ($Gate3Pass) { "PARTIAL" } elseif ($Gate2Pass) { "PARTIAL" } else { "FAIL" }

$PythonVer = (& $VenvPython --version 2>&1).Trim()
$LanceVer  = (& $VenvPython -c "import lancedb; print(lancedb.__version__)" 2>&1).Trim()
$PyiVer    = (& $VenvPython -m PyInstaller --version 2>&1).Trim()
$PySide6Ver= (& $VenvPython -c "import PySide6; print(PySide6.__version__)" 2>&1).Trim()
$TorchVer  = (& $VenvPython -c "import torch; print(torch.__version__)" 2>&1).Trim()
$STVer     = (& $VenvPython -c "import sentence_transformers; print(sentence_transformers.__version__)" 2>&1).Trim()

$ResultsMd = $Results.Keys | ForEach-Object { "| $_ | $($Results[$_]) |" }

$Doc = @"
# LanceDB Windows Packaging Validation V1

Date: $RunDate
Branch: dev/v2
Overall: **$Overall**
Duration: $Duration minutes

## Environment

| Item | Value |
|------|-------|
| Python | $PythonVer |
| Python exe | $($Results["python_exe"]) |
| LanceDB | $LanceVer |
| PySide6 | $PySide6Ver |
| torch (CPU) | $TorchVer |
| sentence-transformers | $STVer |
| PyInstaller | $PyiVer |
| Validation dir | $ValidationDir |

## Gate Results

| Gate | Result |
|------|--------|
$($ResultsMd -join "`n")

## Gate Definitions

- **Gate 1** Import check: torch, transformers, sentence_transformers, lancedb, pyarrow, PySide6
- **Gate 2** Source prototype: ``lancedb_pyside6_prototype.py --headless --search "EV6 battery troubleshooting"``
- **Gate 3** PyInstaller freeze: ``--onefile --collect-all lancedb pyarrow sentence_transformers transformers``
- **Gate 4** Frozen exe: run frozen binary headlessly with the same query

## PyInstaller Command Used

``````powershell
python -m PyInstaller scripts/lancedb_pyside6_prototype.py ``
    --onefile ``
    --collect-all lancedb ``
    --collect-all pyarrow ``
    --collect-all sentence_transformers ``
    --collect-all transformers ``
    --hidden-import PySide6.QtCore ``
    --hidden-import PySide6.QtWidgets ``
    --hidden-import PySide6.QtGui ``
    --noconfirm --clean
``````

## Next Step

$(if ($Overall -eq "PASS") {
    "All four gates passed. Proceed with feat/v2-lancedb-integration: extract SearchEngine into desktop_app/lancedb_engine.py and wire behind an off-by-default settings toggle."
} elseif ($Overall -eq "PARTIAL") {
    "Partial pass. Review FAIL gates above, address the failing dependency, and re-run this script."
} else {
    "Validation failed. Review FAIL details above before starting feat/v2-lancedb-integration."
})
"@

if (-not (Test-Path $DocsInternal)) {
    New-Item -ItemType Directory -Path $DocsInternal -Force | Out-Null
}
$Doc | Set-Content -Path $ResultFile -Encoding UTF8
Write-Pass "Result written to: $ResultFile"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Gate "Summary — Overall: $Overall"
$Results.Keys | ForEach-Object {
    $v = $Results[$_]
    if ($v -like "PASS*") { Write-Pass "$_`: $v" }
    elseif ($v -like "SKIP*") { Write-Info "$_`: $v" }
    else { Write-Fail "$_`: $v" }
}
Write-Host ""
Write-Info "Full results: $ResultFile"
Write-Info "Duration: $Duration minutes"
