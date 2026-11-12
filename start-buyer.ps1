# ================================================================
# Launcher Dimsum Buyer Store (Frontend + Backend)
# ================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  MENJALANKAN WEBSITE SISI BUYER (CUSTOMER STORE)" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

$clientDir = "C:\Users\Zahid\Documents\Project\Dimsum-Client-2026-10-15\dimsum-client"

# 1. Buyer Backend (Port 5000)
Write-Host "[1/2] Menjalankan Buyer Backend (Port 5000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$clientDir'; .\.venv\Scripts\Activate.ps1; Write-Host 'Buyer API aktif di http://127.0.0.1:5000' -ForegroundColor Cyan; python run.py"

Start-Sleep -Seconds 2

# 2. Buyer Frontend (Port 5173)
Write-Host "[2/2] Menjalankan Buyer Frontend (Port 5173)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$clientDir\dimsum-frontend'; Write-Host 'Website Buyer aktif di http://localhost:5173' -ForegroundColor Cyan; npm run dev"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  WEBSITE BUYER TELAH BERJALAN!" -ForegroundColor Green
Write-Host "  👉 Buka di browser: http://localhost:5173" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
