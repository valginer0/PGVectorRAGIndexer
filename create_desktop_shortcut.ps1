# Script to automatically create a Desktop shortcut for the PGVectorRAGIndexer App

$LinkName = "PGVectorRAGIndexer.lnk"
# We define the target batch file that sets up the environment and runs the app
$TargetScriptName = "run_desktop_app.bat"

# Get absolute path to the Launch Script
$TargetScriptPath = Join-Path $PSScriptRoot $TargetScriptName

if (-not (Test-Path $TargetScriptPath)) {
    Write-Host "Error: Could not find launch script at $TargetScriptPath" -ForegroundColor Red
    exit 1
}

# Get the Desktop path for the current user
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath $LinkName

Write-Host "Creating shortcut..."
Write-Host "  Target: $TargetScriptPath"
Write-Host "  Link:   $ShortcutPath"

try {
    # Use WScript.Shell to create the shortcut file
    $WshShell = New-Object -comObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetScriptPath
    $Shortcut.WorkingDirectory = $PSScriptRoot
    $Shortcut.Description = "Launch PGVectorRAGIndexer Desktop App"
    
    # Try to use the Python icon from the virtual environment if it exists
    $VenvPython = Join-Path $PSScriptRoot "venv-windows\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $Shortcut.IconLocation = $VenvPython
    } else {
        # Fallback to a generic icon
        $Shortcut.IconLocation = "shell32.dll,3" 
    }
    
    $Shortcut.Save()
    
    Write-Host "✅ Shortcut created successfully on your Desktop!" -ForegroundColor Green
} catch {
    Write-Host "❌ Error creating shortcut: $_" -ForegroundColor Red
    exit 1
}
