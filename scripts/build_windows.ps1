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
    throw "安装构建依赖失败。"
}

Push-Location $ProjectRoot
try {
    & $VenvPython -m PyInstaller --noconfirm --clean "CardioInsightHolter.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "Windows 应用构建失败。"
    }
}
finally {
    Pop-Location
}

$ExePath = Join-Path $ProjectRoot "dist\CardioInsightHolter\CardioInsightHolter.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "构建失败：未生成 $ExePath"
}

Write-Host "已生成 Windows 应用：$ExePath"
Write-Host "对外分发前请使用受信任的代码签名证书完成 Authenticode 签名。"
