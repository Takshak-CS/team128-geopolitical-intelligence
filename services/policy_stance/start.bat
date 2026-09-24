@echo off
echo Starting Geopolitical Intelligence System...
cd /d C:\santhosh\SEM_6\capstone\DATASETS
start "Backend" python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
timeout /t 5 /nobreak >nul
start "" http://localhost:8000
echo Done! Opening browser...
