# Download ALL Policy Stance datasets from the team GitHub release.
# Safe to re-run: skips files/folders that already exist.
# Called automatically by run_all.ps1 — no manual steps needed.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $Root "services\policy_stance\data"
$CacheDir = Join-Path $Root "services\policy_stance\outputs"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }

# Clear stale cache so module rebuilds from freshly downloaded data
if (Test-Path $CacheDir) {
    Get-ChildItem $CacheDir -Filter "*.pkl" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item "$CacheDir\runtime_manifest.json" -Force -ErrorAction SilentlyContinue
}

$BASE = "https://github.com/Takshak-CS/team128-geopolitical-intelligence/releases/download/policy-data-v1"

function Get-File($name, $dest, $label) {
    if (Test-Path $dest) { Write-Host "  [skip] $label"; return $true }
    Write-Host "  [download] $label ..."
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("User-Agent", "Mozilla/5.0")
        $wc.DownloadFile("$BASE/$name", $dest)
        Write-Host "  [ok] $label"
        return $true
    } catch {
        Write-Host "  [warn] $label failed: $($_.Exception.Message) — will retry next run"
        Remove-Item $dest -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Expand-Zip($zip, $dir, $label) {
    if (Test-Path $dir) { Write-Host "  [skip] $label (already extracted)"; Remove-Item $zip -Force -ErrorAction SilentlyContinue; return }
    if (-not (Test-Path $zip)) { return }
    Write-Host "  [unzip] $label ..."
    try {
        Expand-Archive -Path $zip -DestinationPath $DataDir -Force
        Remove-Item $zip -Force
        Write-Host "  [ok] $label"
    } catch {
        Write-Host "  [warn] $label unzip failed — deleting corrupt file, will retry next run"
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "`nPolicy Stance datasets -> $DataDir`n"

# UN GA voting (the main 544K-vote file)
Get-File "2025_7_23_ga_voting.xlsx" "$DataDir\2025_7_23_ga_voting.xlsx" "UN GA voting 1989-2025 (70 MB)" | Out-Null

# UCDP conflict datasets
$zips = @(
    @{ file="ged251-csv.zip";                    folder="ged251-csv";                    label="UCDP GED 25.1 (28 MB)" },
    @{ file="ucdp-dyadic-251-csv_1.zip";         folder="ucdp-dyadic-251-csv";           label="UCDP Dyadic 25.1" },
    @{ file="ucdp-nonstate-251-csv.zip";         folder="ucdp-nonstate-251-csv";         label="UCDP Non-state 25.1" },
    @{ file="ucdp-onesided-251-csv.zip";         folder="ucdp-onesided-251-csv";         label="UCDP One-sided 25.1" },
    @{ file="ucdp-brd-dyadic-251-csv.zip";       folder="ucdp-brd-dyadic-251-csv";       label="UCDP BRD Dyadic 25.1" },
    @{ file="ucdp-prio-acd-251-csv_1.zip";       folder="ucdp-prio-acd-251-csv";         label="UCDP PRIO ACD 25.1" },
    @{ file="ucdp-actor-251-csv.zip";            folder="ucdp-actor-251-csv";            label="UCDP Actor 25.1" },
    @{ file="organizedviolencecy-251-csv_1.zip"; folder="organizedviolencecy-251-csv";   label="UCDP Organised Violence 25.1" }
)

foreach ($z in $zips) {
    $zipPath = "$DataDir\$($z.file)"
    $folderPath = "$DataDir\$($z.folder)"
    Get-File $z.file $zipPath $z.label | Out-Null
    Expand-Zip $zipPath $folderPath $z.label
}

# Flat CSV/XLSX datasets
$flat = @(
    @{ file="par.csv";                              label="PAR dataset" },
    @{ file="ucdp-candidate-csv.csv";               label="UCDP Candidate" },
    @{ file="ucdp_issues_dataset_dyadyear_232.csv"; label="UCDP Issues" },
    @{ file="CACE_1989-2017.xlsx";                  label="CACE 1989-2017" },
    @{ file="ucdp-peace-agreements-221.xlsx";       label="UCDP Peace Agreements" },
    @{ file="un_votes_clean.xlsx";                  label="UN votes (clean, 59 MB)" }
)

foreach ($f in $flat) {
    Get-File $f.file "$DataDir\$($f.file)" $f.label | Out-Null
}

Write-Host "`nDataset download complete. Any [warn] items will retry on next run."
Write-Host "Policy Stance builds its cache on first start (~8 min)."
