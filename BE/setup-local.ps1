# Script setup backend chạy local trên Windows để truy cập COM ports
# Chạy trong PowerShell: .\setup-local.ps1

Write-Host "=== Setup Backend Local ===" -ForegroundColor Green

# 1. Tạo virtual environment
Write-Host "`n[1/5] Creating virtual environment..." -ForegroundColor Cyan
python -m venv venv

# 2. Activate venv
Write-Host "`n[2/5] Activating virtual environment..." -ForegroundColor Cyan
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
Write-Host "`n[3/5] Installing dependencies..." -ForegroundColor Cyan
pip install --upgrade pip
pip install -r requirements.txt

# 4. Copy .env.local to .env
Write-Host "`n[4/5] Setting up environment variables..." -ForegroundColor Cyan
Copy-Item .env.local .env -Force

# 5. Run migrations
Write-Host "`n[5/5] Running database migrations..." -ForegroundColor Cyan
$env:DATABASE_URL = "postgresql://gait_user:050499@localhost:5433/GaitDB"
alembic upgrade head

Write-Host "`n=== Setup Complete! ===" -ForegroundColor Green
Write-Host "`nTo start the server, run:" -ForegroundColor Yellow
Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor White
