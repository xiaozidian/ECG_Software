param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

$PythonCommand = Get-Command "py.exe" -ErrorAction SilentlyContinue
$PythonArguments = @("-3")
if ($null -eq $PythonCommand) {
    $PythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    $PythonArguments = @()
}
if ($null -eq $PythonCommand) {
    throw "未找到 Python 3。请安装 Python 3.11 或更高版本，并启用 py launcher 或加入 PATH。"
}
$PythonExecutable = $PythonCommand.Source

& $PythonExecutable @PythonArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "需要 Python 3.11 或更高版本。"
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "正在创建本地 Python 环境..."
    & $PythonExecutable @PythonArguments -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "创建 Python 虚拟环境失败。"
    }
}

Write-Host "正在安装运行依赖..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "升级 pip 失败。"
}
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "安装运行依赖失败。"
}

$ConfigPath = Join-Path $ProjectRoot "config.json"
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "config.example.json") -Destination $ConfigPath
    Write-Host "已创建本机配置：$ConfigPath"
}

Write-Host "Windows 运行环境已就绪。"
Write-Host "请确认项目根目录 config.json 中的 data_root 指向本机病例目录。"
