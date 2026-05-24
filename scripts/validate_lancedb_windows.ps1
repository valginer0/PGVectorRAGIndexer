<#
.SYNOPSIS
    Clean-room Windows validation for LanceDB + PySide6 + sentence-transformers packaging.

.DESCRIPTION
    Runs four sequential gates inside a fresh CPython venv (not Anaconda):
      Gate 1a Import check  torch, transformers, sentence_transformers, lancedb, PySide6
      Gate 1b Model load    SentenceTransformer("all-MiniLM-L6-v2") encodes a real non-zero vector
      Gate 2  Source run    lancedb_pyside6_prototype.py --headless (zero-vector fallback = FAIL)
      Gate 3  PyInstaller   freeze prototype to .exe
      Gate 4  Frozen run    frozen .exe --headless (zero-vector fallback = FAIL)

    Results are written to docs/internal/LANCEDB_WINDOWS_VALIDATION_V1.md so they
    can be committed to the private docs branch.

    SCOPE OF PROOF
    --------------
    This script validates "production-online" packaging: the frozen exe can load
    the embedding model and produce real vectors on a machine that has internet
    access and a writable user cache (~/.cache or %USERPROFILE%\.cache).

    It does NOT prove "strict offline/bundled" packaging. Gate 2 populates the
    model cache, and Gate 4 may reuse that cache rather than loading model files
    from inside the exe. If the production requirement is a fully offline,
    no-download, model-inside-installer deployment, a separate offline gate is
    needed:
      - Clear or redirect the HuggingFace/sentence-transformers cache before
        Gate 4 (e.g. set HF_HOME to an empty temp dir).
      - Or run Gate 4 with network access disabled.
    That gate is not implemented here. Add it as Gate 5 when offline deployment
    becomes a hard requirement.

.PARAMETER RepoRoot
    Absolute path to the PGVectorRAGIndexer repository checkout on Windows.
    Default: parent of this script's directory.

.PARAMETER ValidationDir
    Persistent folder for the clean venv and build artefacts.
    Default: C:\Users\<you>\.codex\validation\PGVectorRAGIndexer\clean-cpython-lancedb

.PARAMETER PythonExe
    Path to a python.org CPython executable. Must NOT be Anaconda/Miniconda.
    If omitted the script searches PATH for the first non-Anaconda Python 3.11+.

.PARAMETER RecreateVenv
    Delete the venv, build, and dist folders before starting. Use this for a true
    clean-room run. Without this flag the existing venv is reused (faster for
    iteration, but not a guaranteed clean-room result).

.EXAMPLE
    # Run everything with defaults (reuses existing venv if present)
    .\scripts\validate_lancedb_windows.ps1

.EXAMPLE
    # Full clean-room run: delete venv and rebuild from scratch
    .\scripts\validate_lancedb_windows.ps1 -RecreateVenv

.EXAMPLE
    # Point at a specific CPython install
    .\scripts\validate_lancedb_windows.ps1 -PythonExe "C:\Python311\python.exe" -RecreateVenv
#>

param(
    [string]$RepoRoot      = (Split-Path $PSScriptRoot -Parent),
    [string]$ValidationDir = "$env:USERPROFILE\.codex\validation\PGVectorRAGIndexer\clean-cpython-lancedb",
    [string]$PythonExe     = "",
    [switch]$RecreateVenv
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
# Sanity: warn if RepoRoot looks like a WSL UNC path
# ---------------------------------------------------------------------------
if ($RepoRoot -match "^\\\\wsl") {
    Write-Host ""
    Write-Host "WARNING: RepoRoot appears to be a WSL UNC path:" -ForegroundColor Yellow
    Write-Host "  $RepoRoot" -ForegroundColor Yellow
    Write-Host "PyInstaller is unreliable over \\wsl.localhost\... paths." -ForegroundColor Yellow
    Write-Host "Clone the repo to a native Windows path (e.g. C:\Users\v_ale\PGVectorRAGIndexer)" -ForegroundColor Yellow
    Write-Host "and re-run from there, or pass -RepoRoot explicitly." -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -notmatch "^[Yy]") { exit 1 }
}

# ---------------------------------------------------------------------------
# RecreateVenv: wipe venv, build, dist for a true clean-room run
# ---------------------------------------------------------------------------
if ($RecreateVenv) {
    Write-Info "RecreateVenv: removing venv, build, and dist folders ..."
    foreach ($dir in @("venv", "build", "dist")) {
        $target = Join-Path $ValidationDir $dir
        if (Test-Path $target) {
            Remove-Item $target -Recurse -Force
            Write-Info "  Removed: $target"
        }
    }
    Write-Pass "Clean-room reset complete"
}

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
# Gate 1: Import check + embedding model load + non-zero vector verify
# ---------------------------------------------------------------------------
Write-Gate "Gate 1: Import check and embedding model verification"

# Sub-gate 1a: package imports
$ImportScript = @'
import sys
failed = []
for mod in ["torch", "transformers", "sentence_transformers", "lancedb", "pyarrow", "PySide6"]:
    try:
        __import__(mod)
    except Exception as e:
        failed.append(f"{mod}: {e}")
if failed:
    print("IMPORT_FAIL")
    for f in failed: print(f"  {f}")
    sys.exit(1)
else:
    print("IMPORT_PASS")
    sys.exit(0)
'@

Write-Info "Sub-gate 1a: package imports ..."
$ImportResult = & $VenvPython -c $ImportScript 2>&1
$Gate1aPass = $LASTEXITCODE -eq 0
if ($Gate1aPass) {
    Write-Pass "All packages import successfully"
    $Results["gate1a_imports"] = "PASS"
} else {
    Write-Fail "Import failures:"
    $ImportResult | ForEach-Object { Write-Info $_ }
    $Results["gate1a_imports"] = "FAIL: $($ImportResult | Select-Object -Last 5)"
}

# Sub-gate 1b: load the actual embedding model and verify a real vector
# This is the critical check that a zero-vector fallback would mask.
$ModelScript = @'
import sys
MODEL_NAME = "all-MiniLM-L6-v2"
EXPECTED_DIM = 384
try:
    from sentence_transformers import SentenceTransformer
    print(f"Loading {MODEL_NAME} ...", flush=True)
    model = SentenceTransformer(MODEL_NAME)
    vec = model.encode("EV6 battery diagnostic")
    if hasattr(vec, "tolist"):
        vec = vec.tolist()
    dim = len(vec)
    if dim != EXPECTED_DIM:
        print(f"MODEL_FAIL: expected {EXPECTED_DIM} dims, got {dim}")
        sys.exit(1)
    if all(v == 0.0 for v in vec):
        print("MODEL_FAIL: all-zero vector - model loaded but did not encode")
        sys.exit(1)
    nonzero = sum(1 for v in vec if v != 0.0)
    print(f"MODEL_PASS: {dim}-dim vector, {nonzero} non-zero values, first=[{vec[0]:.4f}, {vec[1]:.4f}, ...]")
    sys.exit(0)
except Exception as e:
    print(f"MODEL_FAIL: {e}")
    sys.exit(1)
'@

Write-Info "Sub-gate 1b: load SentenceTransformer('all-MiniLM-L6-v2') and encode a sentence ..."
Write-Info "(Model will be downloaded on first run - may take a minute)"
$ModelResult = & $VenvPython -c $ModelScript 2>&1
$Gate1bPass = $LASTEXITCODE -eq 0
if ($Gate1bPass) {
    Write-Pass ($ModelResult | Select-String "MODEL_PASS" | Select-Object -First 1)
    $Results["gate1b_embedding_model"] = "PASS: $($ModelResult | Select-String 'MODEL_PASS')"
} else {
    Write-Fail "Embedding model check failed:"
    $ModelResult | ForEach-Object { Write-Info $_ }
    $Results["gate1b_embedding_model"] = "FAIL: $($ModelResult | Select-Object -Last 3)"
}

$Gate1Pass = $Gate1aPass -and $Gate1bPass

# ---------------------------------------------------------------------------
# Gate 2: Source prototype headless run (zero-vector fallback is a FAIL)
# ---------------------------------------------------------------------------
Write-Gate "Gate 2: Source prototype headless run"

$ProtoScript  = Join-Path $RepoRoot "scripts\lancedb_pyside6_prototype.py"
$ProtoLanceDir = Join-Path $ValidationDir "lancedb_data"

# These strings appear in stderr when sentence-transformers fails to load and
# the prototype silently falls back to zero vectors. A run that exits 0 but
# emits either string must be treated as a failure.
$ZeroVectorMarkers = @(
    "Falling back to zero-vector representations",
    "sentence_transformers could not be loaded"
)

function Test-ZeroVectorFallback {
    param([string[]]$Output)
    foreach ($marker in $ZeroVectorMarkers) {
        if ($Output -match [regex]::Escape($marker)) { return $true }
    }
    return $false
}

if ($Gate1Pass) {
    $ProtoOutput = & $VenvPython $ProtoScript `
        --headless `
        --search "EV6 battery troubleshooting" `
        --lance-path $ProtoLanceDir 2>&1
    $ExitedClean = $LASTEXITCODE -eq 0
    $UsedFallback = Test-ZeroVectorFallback $ProtoOutput
    $Gate2Pass = $ExitedClean -and -not $UsedFallback
    if ($Gate2Pass) {
        Write-Pass "Headless run exited cleanly with real embedding model"
        $Results["gate2_source_run"] = "PASS"
    } elseif ($UsedFallback) {
        Write-Fail "Headless run used zero-vector fallback - embedding model failed inside prototype"
        $ProtoOutput | Where-Object { $_ -match "zero-vector|sentence_transformers" } |
            ForEach-Object { Write-Info $_ }
        $Results["gate2_source_run"] = "FAIL: zero-vector fallback detected"
    } else {
        Write-Fail "Headless run failed (exit code non-zero):"
        $ProtoOutput | Select-Object -Last 20 | ForEach-Object { Write-Info $_ }
        $Results["gate2_source_run"] = "FAIL: non-zero exit"
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
# Gate 4: Frozen exe headless run (zero-vector fallback is a FAIL)
# ---------------------------------------------------------------------------
Write-Gate "Gate 4: Frozen exe headless run"

if ($Gate3Pass) {
    $FrozenLanceDir = Join-Path $ValidationDir "lancedb_data_frozen"
    $FrozenOutput = & $FrozenExe `
        --headless `
        --search "EV6 battery troubleshooting" `
        --lance-path $FrozenLanceDir 2>&1
    $ExitedClean  = $LASTEXITCODE -eq 0
    $UsedFallback = Test-ZeroVectorFallback $FrozenOutput
    $Gate4Pass = $ExitedClean -and -not $UsedFallback
    if ($Gate4Pass) {
        Write-Pass "Frozen exe ran headlessly with real embedding model"
        $Results["gate4_frozen_run"] = "PASS"
    } elseif ($UsedFallback) {
        # This is the critical case: PyInstaller froze source correctly but
        # sentence-transformers or its data files were not bundled properly.
        Write-Fail "Frozen exe used zero-vector fallback - model not properly bundled by PyInstaller"
        $FrozenOutput | Where-Object { $_ -match "zero-vector|sentence_transformers" } |
            ForEach-Object { Write-Info $_ }
        $Results["gate4_frozen_run"] = "FAIL: zero-vector fallback in frozen exe (bundling incomplete)"
    } else {
        Write-Fail "Frozen exe failed (exit code non-zero):"
        $FrozenOutput | Select-Object -Last 20 | ForEach-Object { Write-Info $_ }
        $Results["gate4_frozen_run"] = "FAIL: non-zero exit"
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

## Scope Of Proof

This validation proves **production-online packaging**: the frozen executable can
load the embedding model and produce real vectors on a Windows machine with
network access and a writable user cache.

This validation does **not** prove strict offline/bundled-model packaging. Gate 2
may populate the HuggingFace/sentence-transformers cache before Gate 4 runs, so
Gate 4 may load model files from that cache rather than from inside the frozen
executable. If fully offline deployment becomes a hard requirement, add a Gate 5
that clears or redirects the model cache (for example by setting ``HF_HOME`` to
an empty temp directory) before running the frozen executable, or run Gate 4 with
network access disabled and an empty cache.

## Gate Definitions

- **Gate 1a** Import check: torch, transformers, sentence_transformers, lancedb, pyarrow, PySide6
- **Gate 1b** Embedding model: load ``SentenceTransformer("all-MiniLM-L6-v2")``, encode one sentence, verify 384-dim non-zero vector (catches zero-vector fallback masking a real model failure)
- **Gate 2** Source prototype: ``lancedb_pyside6_prototype.py --headless --search "EV6 battery troubleshooting"`` - exits cleanly AND output must not contain zero-vector fallback markers
- **Gate 3** PyInstaller freeze: ``--onefile --collect-all lancedb pyarrow sentence_transformers transformers``
- **Gate 4** Frozen exe: run frozen binary headlessly with same query - exits cleanly AND output must not contain zero-vector fallback markers (catches PyInstaller bundling incomplete sentence-transformers data)

## How to Re-run

``````powershell
# Reuse existing venv (fast, for iteration)
.\scripts\validate_lancedb_windows.ps1

# Full clean-room run (delete venv/build/dist and start fresh)
.\scripts\validate_lancedb_windows.ps1 -RecreateVenv
``````

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
Write-Gate "Summary - Overall: $Overall"
$Results.Keys | ForEach-Object {
    $v = $Results[$_]
    if ($v -like "PASS*") { Write-Pass "$_`: $v" }
    elseif ($v -like "SKIP*") { Write-Info "$_`: $v" }
    else { Write-Fail "$_`: $v" }
}
Write-Host ""
Write-Info "Full results: $ResultFile"
Write-Info "Duration: $Duration minutes"
