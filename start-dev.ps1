param(
    [switch]$NoNewWindow,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [switch]$KillBackendPortOwner
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendEntry = Join-Path $backendDir "app\main.py"
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
$npmCmd = if ($npm) { $npm.Source } else { $null }

if (-not (Test-Path $venvPython)) {
    throw "Cannot find $venvPython. Ensure .venv exists in project root."
}

if (-not (Test-Path $backendEntry)) {
    throw "Cannot find backend entry: $backendEntry"
}

if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    throw "Cannot find frontend package.json: $frontendDir"
}

if (-not $npmCmd) {
    throw "Cannot find npm.cmd. Ensure Node.js is installed and in PATH."
}

function Get-ListeningPidByPort {
    param(
        [int]$Port
    )
    $line = netstat -ano | Select-String -Pattern ("127.0.0.1:{0}\s+.*LISTENING\s+(\d+)$" -f $Port) | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    $match = [regex]::Match($line.Line, "LISTENING\s+(\d+)$")
    if (-not $match.Success) {
        return $null
    }
    return [int]$match.Groups[1].Value
}

$existingBackendPid = Get-ListeningPidByPort -Port $BackendPort
if ($existingBackendPid) {
    if ($KillBackendPortOwner) {
        Write-Host "Port $BackendPort is occupied by PID $existingBackendPid. Stopping it..."
        Stop-Process -Id $existingBackendPid -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 500
    }
    else {
        throw "Backend port $BackendPort is occupied by PID $existingBackendPid. Run: Stop-Process -Id $existingBackendPid -Force, or restart with -KillBackendPortOwner."
    }
}

$backendCommand = @(
    "Set-Location `"$projectRoot`""
    "& `"$venvPython`" -m uvicorn app.main:app --reload --app-dir backend --port $BackendPort"
) -join "; "

$frontendCommand = @(
    "Set-Location `"$frontendDir`""
    "`$env:VITE_BACKEND_PORT=`"$BackendPort`""
    "`$env:VITE_FRONTEND_PORT=`"$FrontendPort`""
    "& `"$npmCmd`" run dev -- --port $FrontendPort"
) -join "; "

if ($NoNewWindow) {
    Write-Host "Starting backend..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $backendCommand)
    Write-Host "Starting frontend..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $frontendCommand)
}
else {
    Write-Host "Starting backend in a new window..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $backendCommand) -WindowStyle Normal
    Write-Host "Starting frontend in a new window..."
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $frontendCommand) -WindowStyle Normal
}

Write-Host ""
Write-Host "Launch commands submitted:"
Write-Host "- Backend: http://127.0.0.1:$BackendPort"
Write-Host "- Frontend: http://127.0.0.1:$FrontendPort"
Write-Host ""
Write-Host "Make sure MinIO and Milvus are already running."
