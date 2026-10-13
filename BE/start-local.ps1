# Script khởi động backend local
# Chạy trong PowerShell: .\start-local.ps1

Write-Host "=== Starting Backend Server ===" -ForegroundColor Green

# Activate venv
Write-Host "`nActivating virtual environment..." -ForegroundColor Cyan
.\venv\Scripts\Activate.ps1

# Set environment
$env:DATABASE_URL = "postgresql://gait_user:050499@localhost:5433/GaitDB"

# Start server
Write-Host "`nStarting Uvicorn server on http://localhost:8000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop`n" -ForegroundColor Yellow

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
