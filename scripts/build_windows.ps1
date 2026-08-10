param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & (Join-Path $PSScriptRoot "setup_windows.ps1")
}

& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build dependencies."
}

Push-Location $ProjectRoot
try {
    & $VenvPython -m PyInstaller --noconfirm --clean "CardioInsightHolter.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "Windows application build failed."
    }
}
finally {
    Pop-Location
}

$ExePath = Join-Path $ProjectRoot "dist\CardioInsightHolter\CardioInsightHolter.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build failed: executable was not generated at $ExePath"
}

Write-Host "Windows application generated at: $ExePath"
Write-Host "Sign the application with a trusted Authenticode certificate before external distribution."
