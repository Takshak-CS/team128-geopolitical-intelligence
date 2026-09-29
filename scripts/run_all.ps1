# Start all five services on this machine (Windows PowerShell).
#
#   scripts\setup_local.ps1     once, to create .venv
#   scripts\run_all.ps1         start everything, wait until healthy
#   scripts\stop_all.ps1        stop everything
#
# Logs go to .run\logs\<service>.log. Open http://127.0.0.1:8000 when it reports ready.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "No .venv found. Run scripts\setup_local.ps1 first." }

$LogDir = Join-Path $Root ".run\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

$Services = @(
    @{ Name = "soft_power";          Port = 8101; Dir = "services\soft_power\dash\backend"; App = "app.main:app";     Env = @{ DATA_SOURCE = "files" } },
    @{ Name = "policy_stance";       Port = 8102; Dir = "services\policy_stance";           App = "backend.main:app"; Env = @{} },
    @{ Name = "trade_intelligence";  Port = 8103; Dir = "services\trade_intelligence";      App = "api.app:app";      Env = @{ TRADE_CACHE_DIR = (Join-Path $Root "services\trade_intelligence\cache") } },
    @{ Name = "event_summarization"; Port = 8104; Dir = "services\event_summarization";     App = "src.api:app";      Env = @{} },
    @{ Name = "orchestrator";        Port = 8000; Dir = "orchestrator";                     App = "app.main:app";     Env = @{} }
)

# Ensure Policy Stance datasets are present before starting any service
Write-Host "Checking Policy Stance datasets..."
& "$PSScriptRoot\download_policy_data.ps1"

foreach ($svc in $Services) {
    $busy = Get-NetTCPConnection -LocalPort $svc.Port -State Listen -ErrorAction SilentlyContinue
    if ($busy) { Write-Host ("{0,-20} port {1} already in use - skipping" -f $svc.Name, $svc.Port); continue }
    foreach ($key in $svc.Env.Keys) { Set-Item -Path "Env:$key" -Value $svc.Env[$key] }
    $log = Join-Path $LogDir "$($svc.Name).log"
    $proc = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", $svc.App, "--host", "127.0.0.1", "--port", $svc.Port) `
        -WorkingDirectory (Join-Path $Root $svc.Dir) `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
        -WindowStyle Hidden -PassThru
    Write-Host ("{0,-20} starting on :{1} (pid {2})" -f $svc.Name, $svc.Port, $proc.Id)
}

Write-Host "`nWaiting for health checks (Policy Stance can take several minutes on its first build)..."
$deadline = (Get-Date).AddMinutes(15)
$checks = @{ soft_power = "http://127.0.0.1:8101/health"; trade_intelligence = "http://127.0.0.1:8103/health"; event_summarization = "http://127.0.0.1:8104/health"; orchestrator = "http://127.0.0.1:8000/health"; policy_stance = "http://127.0.0.1:8102/status" }
$pending = [System.Collections.ArrayList]@($checks.Keys)
while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
    foreach ($name in @($pending)) {
        try {
            $body = Invoke-RestMethod -Uri $checks[$name] -TimeoutSec 3
            if ($name -eq "policy_stance" -and -not $body.ready) { continue }
            Write-Host ("  ready: {0}" -f $name)
            $pending.Remove($name)
        } catch { }
    }
    if ($pending.Count -gt 0) { Start-Sleep -Seconds 3 }
}
if ($pending.Count -gt 0) { Write-Host ("Still starting: {0}. Check .run\logs." -f ($pending -join ", ")) }
Write-Host "`nBriefing UI:  http://127.0.0.1:8000"
Write-Host "API docs:     http://127.0.0.1:8000/docs"
