# One-time local setup: a single virtualenv that can run all five services.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m spacy download en_core_web_sm

Write-Host "`nSetup done. Data each service needs is listed in docs\DATA.md."
Write-Host "Then run: scripts\run_all.ps1"
