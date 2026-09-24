# Optional: start each module's own dashboard, pointed at its agent's platform port,
# so the "Open module dashboard" links in the briefing UI work.
#
#   Soft Power     http://localhost:5174   (React + Vite)
#   Policy Stance  http://localhost:5175   (React + Vite)
#   Trade          http://localhost:8080/?api=http://127.0.0.1:8103   (static page)
#   Events         http://localhost:5176   (React + Vite)
#
# The first run installs each app's npm dependencies.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root ".run\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

$Apps = @(
    @{ Name = "soft_power_ui";    Dir = "services\soft_power\dash\frontend";      Port = 5174; Env = @{ VITE_API_BASE_URL = "http://127.0.0.1:8101" } },
    @{ Name = "policy_stance_ui"; Dir = "services\policy_stance\frontend";        Port = 5175; Env = @{ VITE_API_BASE = "http://127.0.0.1:8102"; VITE_API_BASE_URL = "http://127.0.0.1:8102" } },
    @{ Name = "events_ui";        Dir = "services\event_summarization\frontend";  Port = 5176; Env = @{ VITE_API_URL = "http://127.0.0.1:8104" } }
)

foreach ($app in $Apps) {
    $dir = Join-Path $Root $app.Dir
    if (-not (Test-Path (Join-Path $dir "node_modules"))) {
        Write-Host "npm install in $($app.Dir) ..."
        Push-Location $dir; npm install --no-audit --no-fund | Out-Null; Pop-Location
    }
    foreach ($key in $app.Env.Keys) { Set-Item -Path "Env:$key" -Value $app.Env[$key] }
    $log = Join-Path $LogDir "$($app.Name).log"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "npx vite --port $($app.Port) --strictPort") -WorkingDirectory $dir `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden | Out-Null
    Write-Host ("{0,-18} http://localhost:{1}" -f $app.Name, $app.Port)
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
Start-Process -FilePath $python -ArgumentList @("-m", "http.server", "8080", "--directory", (Join-Path $Root "services\trade_intelligence\frontend")) `
    -RedirectStandardOutput (Join-Path $LogDir "trade_ui.log") -RedirectStandardError (Join-Path $LogDir "trade_ui.log.err") -WindowStyle Hidden | Out-Null
Write-Host ("{0,-18} http://localhost:8080/?api=http://127.0.0.1:8103" -f "trade_ui")
