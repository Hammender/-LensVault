param(
    [switch]$NoNewWindow
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendEntry = Join-Path $backendDir "app\main.py"
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)?.Source

if (-not (Test-Path $venvPython)) {
    throw "未找到 $venvPython。请确认 .venv 在项目根目录。"
}

if (-not (Test-Path $backendEntry)) {
    throw "未找到后端入口文件: $backendEntry"
}

if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    throw "未找到前端 package.json: $frontendDir"
}

if (-not $npmCmd) {
    throw "未找到 npm.cmd，请确认 Node.js 已安装并加入 PATH。"
}

$backendCommand = @(
    "Set-Location `"$projectRoot`""
    "& `"$venvPython`" -m uvicorn app.main:app --reload --app-dir backend"
) -join "; "

$frontendCommand = @(
    "Set-Location `"$frontendDir`""
    "& `"$npmCmd`" run dev"
) -join "; "

if ($NoNewWindow) {
    Write-Host "启动后端..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $backendCommand)
    Write-Host "启动前端..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $frontendCommand)
}
else {
    Write-Host "在新窗口启动后端..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $backendCommand) -WindowStyle Normal
    Write-Host "在新窗口启动前端..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $frontendCommand) -WindowStyle Normal
}

Write-Host ""
Write-Host "服务启动命令已下发："
Write-Host "- 后端: http://127.0.0.1:8000"
Write-Host "- 前端: http://127.0.0.1:5173"
Write-Host ""
Write-Host "注意：请先确保 MinIO 已运行。"
