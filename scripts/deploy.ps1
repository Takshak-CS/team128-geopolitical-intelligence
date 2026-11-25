# Deploy (or update) the whole system on one Linux server over SSH.
#
#   scripts\set_password.ps1                                   once: choose the login
#   scripts\deploy.ps1 -Server ubuntu@203.0.113.10 -Key C:\keys\team128.pem
#   scripts\deploy.ps1 -Server ubuntu@203.0.113.10 -Key ... -SkipData    code-only update
#   scripts\deploy.ps1 -Server ubuntu@203.0.113.10 -Key ... -Public      no login: anyone with the link
#   scripts\deploy.ps1 -Server ubuntu@203.0.113.10 -Key ... -SkipData -FromGitHub   fast: the server fetches main
#
# By default it uploads the current working tree (tracked + new, not ignored files)
# and, unless -SkipData, the datasets that are not in git. The server needs nothing
# but Ubuntu and sudo.
#
# -FromGitHub deploys what is on GitHub instead: the laptop sends only a 1 KB script,
# and the server downloads the latest commit of -Ref (default main) itself and builds
# it in the background. It is much faster on a slow connection, and a dropped SSH
# session does not stop the build. Push first: local commits that are not on GitHub
# are refused, and uncommitted edits are not deployed. See docs/DEPLOY.md.
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$Key = "",
    [string]$Site = "",
    [switch]$SkipData,
    [switch]$Public,
    [switch]$FromGitHub,
    [string]$Ref = "main",
    [string]$Repo = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Native([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

$auth = Join-Path $Root "deploy\.auth"
if (-not $Public -and -not (Test-Path $auth)) { throw "No login chosen yet. Run scripts\set_password.ps1 first, or pass -Public to serve the site without one." }
$access = if ($Public) { "public" } else { "login" }
if ($Key -and -not (Test-Path $Key)) { throw "SSH key not found: $Key" }

$hostPart = $Server.Split("@")[-1]
if (-not $Site) {
    # sslip.io maps <ip>.sslip.io to <ip>, which lets Caddy get a real HTTPS certificate without a domain.
    $Site = if ($hostPart -match '^\d{1,3}(\.\d{1,3}){3}$') { "$hostPart.sslip.io" } else { $hostPart }
}
$sshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30")
if ($Key) { $sshOpts += @("-i", $Key) }

$out = Join-Path $Root ".run\deploy"
New-Item -ItemType Directory -Force $out | Out-Null

if ($FromGitHub) {
    # Which repository and commit: the one GitHub has for -Ref, checked against this checkout.
    if (-not $Repo) {
        $remote = (git remote get-url origin).Trim()
        if ($remote -match 'github\.com(?::\d+)?[:/]([^/]+)/([^/]+?)(\.git)?/?$') { $Repo = "$($Matches[1])/$($Matches[2])" }
        else { throw "Could not tell the GitHub repository from origin ($remote). Pass -Repo owner/name." }
    }
    Invoke-Native "git fetch" { git fetch --quiet origin $Ref }
    $commit = (git rev-parse "origin/$Ref").Trim()
    $unpushed = [int](git rev-list --count "origin/$Ref..HEAD")
    if ($unpushed -gt 0) { throw "$unpushed local commit(s) are not on GitHub's $Ref yet. Push first (git push origin $Ref), then deploy." }
    $dirty = git status --porcelain --untracked-files=no
    if ($dirty) { Write-Host "   Not deployed (uncommitted): $(@($dirty).Count) file(s), e.g. $((@($dirty)[0]).Trim())" -ForegroundColor Yellow }
    Write-Host ("== Deploying {0} at {1}: {2}" -f $Repo, $commit.Substring(0, 7), (git log -1 --format=%s $commit))

    $upload = @((Join-Path $Root "deploy\remote_from_github.sh"))
    if (-not $Public) { $upload += $auth }
    if (-not $SkipData) {
        Write-Host "== Packaging data"
        $data = @("services/trade_intelligence/cache", "services/policy_stance/data", "services/event_summarization/data/dyad_geopolitical_scores.csv")
        foreach ($item in $data) { if (-not (Test-Path $item)) { throw "Missing $item - see docs/DATA.md" } }
        Invoke-Native "packaging data" { tar -czf (Join-Path $out "data.tar.gz") @data }
        Write-Host ("   {0:N1} MB" -f ((Get-Item (Join-Path $out "data.tar.gz")).Length / 1MB))
        $upload += (Join-Path $out "data.tar.gz")
    }

    Write-Host "== Starting the build on $Server"
    Invoke-Native "ssh" { ssh @sshOpts $Server "mkdir -p ~/team128-upload" }
    Invoke-Native "scp" { scp @sshOpts @upload "${Server}:team128-upload/" }
    Invoke-Native "remote start" { ssh @sshOpts $Server "bash ~/team128-upload/remote_from_github.sh '$Repo' '$commit' '$Site' $access" }

    # Follow the log. Connection drops only delay this; the build keeps going on the server.
    Write-Host "== Building on the server (about 5 minutes; longer when images change)"
    $deadline = (Get-Date).AddMinutes(45)
    $exitCode = $null
    $ErrorActionPreference = "Continue"
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 20
        $tail = & ssh @sshOpts -o ConnectTimeout=15 $Server "tail -n 2 ~/team128-upload/setup.log"
        if ($LASTEXITCODE -ne 0) { Write-Host "   (no connection to the server, still waiting)"; continue }
        $text = ($tail | Out-String)
        if ($text -match "SETUP_EXIT=(\d+)") { $exitCode = [int]$Matches[1]; break }
        $last = ($text.Trim() -split "`n" | Select-Object -Last 1)
        if ($last) { Write-Host "   $last" }
    }
    $ErrorActionPreference = "Stop"
    if ($null -eq $exitCode) { throw "The build did not finish within 45 minutes. See ~/team128-upload/setup.log on the server." }
    & ssh @sshOpts $Server "tail -n 12 ~/team128-upload/setup.log"
    if ($exitCode -ne 0) { throw "Server setup failed (exit $exitCode). See ~/team128-upload/setup.log on the server." }
    $url = if ($Site -like "http://*") { $Site } else { "https://$Site" }
    Write-Host "`nDeployed $($commit.Substring(0, 7)): $url"
    return
}

Write-Host "== Packaging code"
$files = git -c core.quotepath=false ls-files -co --exclude-standard | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
[IO.File]::WriteAllLines((Join-Path $out "files.txt"), [string[]]$files)
Invoke-Native "packaging code" { tar -czf (Join-Path $out "code.tar.gz") -T (Join-Path $out "files.txt") }
Write-Host ("   {0} files, {1:N1} MB" -f $files.Count, ((Get-Item (Join-Path $out "code.tar.gz")).Length / 1MB))

$upload = @((Join-Path $out "code.tar.gz"), (Join-Path $Root "deploy\remote_setup.sh"))
if (-not $Public) { $upload += $auth }
if (-not $SkipData) {
    Write-Host "== Packaging data"
    $data = @("services/trade_intelligence/cache", "services/policy_stance/data", "services/event_summarization/data/dyad_geopolitical_scores.csv")
    foreach ($item in $data) { if (-not (Test-Path $item)) { throw "Missing $item - see docs/DATA.md" } }
    Invoke-Native "packaging data" { tar -czf (Join-Path $out "data.tar.gz") @data }
    Write-Host ("   {0:N1} MB" -f ((Get-Item (Join-Path $out "data.tar.gz")).Length / 1MB))
    $upload += (Join-Path $out "data.tar.gz")
}

Write-Host "== Uploading to $Server"
Invoke-Native "ssh" { ssh @sshOpts $Server "mkdir -p ~/team128-upload" }
Invoke-Native "scp" { scp @sshOpts @upload "${Server}:team128-upload/" }

Write-Host "== Installing and starting on the server"
Invoke-Native "remote setup" { ssh @sshOpts $Server "bash ~/team128-upload/remote_setup.sh '$Site' $access" }

$url = if ($Site -like "http://*") { $Site } else { "https://$Site" }
Write-Host "`nDeployed: $url"
