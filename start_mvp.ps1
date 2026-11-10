# ============================================================================
# IoT Smart Locker MVP - One-Click Startup Script (Windows PowerShell)
# Starts MySQL 8.0 (Port 3306), FastAPI Backend (Port 8000), and Streamlit UI (Port 8501)
# ============================================================================

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  IoT SMART LOCKER MVP (YOLOv5 + FastAPI + MySQL + ESP32)   " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Ensure MySQL 8.0 is running on 127.0.0.1:3306 if installed
$mysqlBin = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe"
$mysqlData = Join-Path $ProjectRoot "data\mysql_data"
$port3306 = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue

if (-not $port3306 -and (Test-Path $mysqlBin)) {
    if (-not (Test-Path "$mysqlData\mysql")) {
        Write-Host "[1/3] Initializing local MySQL 8.0 data directory..." -ForegroundColor Yellow
        New-Item -ItemType Directory -Force -Path $mysqlData | Out-Null
        & $mysqlBin --initialize-insecure --datadir="$mysqlData"
    }
    Write-Host "[1/3] Starting MySQL 8.0 Server on 127.0.0.1:3306..." -ForegroundColor Green
    Start-Process -FilePath $mysqlBin -ArgumentList "--datadir=`"$mysqlData`"", "--port=3306", "--bind-address=127.0.0.1" -WindowStyle Hidden
    Start-Sleep -Seconds 3
} else {
    Write-Host "[1/3] MySQL 8.0 Server is already active on port 3306." -ForegroundColor Green
}

# 2. Start FastAPI Backend on http://127.0.0.1:8000
$port8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $port8000) {
    Write-Host "[2/3] Starting FastAPI Backend on http://127.0.0.1:8000 ..." -ForegroundColor Green
    Start-Process -FilePath "$ProjectRoot\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $ProjectRoot
    Start-Sleep -Seconds 2
} else {
    Write-Host "[2/3] FastAPI Backend is already listening on http://127.0.0.1:8000" -ForegroundColor Green
}

# 3. Start Streamlit Unified Kiosk & Dashboard on http://127.0.0.1:8501
Write-Host "[3/3] Starting Streamlit Kiosk & Dashboard UI on http://127.0.0.1:8501 ..." -ForegroundColor Green
& "$ProjectRoot\.venv\Scripts\streamlit.exe" run "$ProjectRoot\frontend\app.py" --server.port 8501

