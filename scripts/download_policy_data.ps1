# Download Policy Stance datasets automatically.
# UCDP files come from the official UCDP website.
# UN GA voting file comes from Google Drive (set $UN_GDRIVE_ID below).
#
# Usage:  scripts\download_policy_data.ps1
# Safe to re-run: skips files that already exist.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$DataDir = Join-Path $Root "services\policy_stance\data"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }

# ── Google Drive file ID for 2025_7_23_ga_voting.xlsx ─────────────────────────
# Santhosh: upload the file to Google Drive, share as "Anyone with the link",
# then paste the file ID (the long string in the share URL) here.
$UN_GDRIVE_ID = "PASTE_GDRIVE_FILE_ID_HERE"
# ──────────────────────────────────────────────────────────────────────────────

function Download-File($Url, $Dest, $Label) {
    if (Test-Path $Dest) {
        Write-Host "  [skip] $Label already exists"
        return
    }
    Write-Host "  [download] $Label ..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($Url, $Dest)
        Write-Host "  [ok] $Label"
    } catch {
        Write-Host "  [error] Failed to download $Label : $_"
        throw
    }
}

function Expand-Zip($ZipPath, $DestDir) {
    Write-Host "  [unzip] $(Split-Path $ZipPath -Leaf) ..."
    Expand-Archive -Path $ZipPath -DestinationPath $DestDir -Force
    Remove-Item $ZipPath
}

Write-Host "`nPolicy Stance dataset setup"
Write-Host "Target: $DataDir`n"

# ── UCDP 25.1 datasets (official public downloads) ────────────────────────────
$ucdp = @(
    @{ url = "https://ucdp.uu.se/downloads/dyadic/ucdp-dyadic-251-csv.zip";        label = "UCDP Dyadic 25.1" },
    @{ url = "https://ucdp.uu.se/downloads/ged/ged251-csv.zip";                     label = "UCDP GED 25.1" },
    @{ url = "https://ucdp.uu.se/downloads/nsos/ucdp-nonstate-251-csv.zip";         label = "UCDP Non-state 25.1" },
    @{ url = "https://ucdp.uu.se/downloads/ucdp-onesided/ucdp-onesided-251-csv.zip"; label = "UCDP One-sided 25.1" },
    @{ url = "https://ucdp.uu.se/downloads/brd/ucdp-brd-dyadic-251-csv.zip";        label = "UCDP BRD Dyadic 25.1" }
)

foreach ($d in $ucdp) {
    $zipName = Split-Path $d.url -Leaf
    $zipPath = Join-Path $DataDir $zipName
    $folderName = $zipName -replace "\.zip$", ""
    $folderPath = Join-Path $DataDir $folderName
    if (Test-Path $folderPath) {
        Write-Host "  [skip] $($d.label) folder already exists"
        continue
    }
    Download-File $d.url $zipPath $d.label
    Expand-Zip $zipPath $DataDir
}

# ── UN GA voting file (Google Drive) ──────────────────────────────────────────
$unFile = Join-Path $DataDir "2025_7_23_ga_voting.xlsx"
if (Test-Path $unFile) {
    Write-Host "  [skip] UN GA voting file already exists"
} elseif ($UN_GDRIVE_ID -eq "PASTE_GDRIVE_FILE_ID_HERE") {
    Write-Host ""
    Write-Host "  [action required] UN GA voting file not configured."
    Write-Host "  Ask Santhosh for the Google Drive link, or download manually:"
    Write-Host "  https://digitallibrary.un.org/record/4060887 -> Export -> Excel"
    Write-Host "  Save as: $unFile"
    Write-Host ""
    Write-Host "  (Policy Stance will still run on UCDP data alone until this file is added)"
} else {
    $gdUrl = "https://drive.google.com/uc?export=download&id=$UN_GDRIVE_ID"
    Download-File $gdUrl $unFile "UN GA voting 2025"
}

Write-Host "`nDone. Start Policy Stance with:  scripts\run_all.ps1"
Write-Host "First run takes ~8 minutes to build the cache. Subsequent starts: <1 minute."
