# One-time local setup: a single virtualenv that can run all five services.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe -m spacy download en_core_web_sm

Write-Host "`nDownloading Policy Stance datasets..."
& "$PSScriptRoot\download_policy_data.ps1"

Write-Host "`nSetup done. Run: scripts\run_all.ps1"
