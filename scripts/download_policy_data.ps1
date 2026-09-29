# Download ALL Policy Stance datasets from the team GitHub release.
# Safe to re-run: skips files/folders that already exist.
# Called automatically by setup_local.ps1 — no manual steps needed.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $Root "services\policy_stance\data"
$CacheDir = Join-Path $Root "services\policy_stance\outputs"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }

# Clear any stale cache so the module rebuilds from the freshly downloaded data
if (Test-Path $CacheDir) {
    Get-ChildItem $CacheDir -Filter "*.pkl" | Remove-Item -Force
    Get-ChildItem $CacheDir -Filter "runtime_manifest.json" | Remove-Item -Force -ErrorAction SilentlyContinue
}

$BASE = "https://github.com/Takshak-CS/team128-geopolitical-intelligence/releases/download/policy-data-v1"

function Get-File($name, $dest, $label) {
    if (Test-Path $dest) { Write-Host "  [skip] $label"; return }
    Write-Host "  [download] $label ..."
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "Mozilla/5.0")
    $wc.DownloadFile("$BASE/$name", $dest)
    Write-Host "  [ok] $label"
}

function Expand-Zip($zip, $dir, $label) {
    if (Test-Path $dir) { Write-Host "  [skip] $label (already extracted)"; Remove-Item $zip -ErrorAction SilentlyContinue; return }
    Write-Host "  [unzip] $label ..."
    Expand-Archive -Path $zip -DestinationPath $DataDir -Force
    Remove-Item $zip
    Write-Host "  [ok] $label"
}

Write-Host "`nPolicy Stance datasets -> $DataDir`n"

# UN GA voting (the main 544K-vote file)
Get-File "2025_7_23_ga_voting.xlsx" "$DataDir\2025_7_23_ga_voting.xlsx" "UN GA voting 1989-2025 (70 MB)"

# UCDP conflict datasets
$zips = @(
    @{ file="ged251-csv.zip";              folder="ged251-csv";              label="UCDP GED 25.1 (28 MB)" },
    @{ file="ucdp-dyadic-251-csv_1.zip";   folder="ucdp-dyadic-251-csv";     label="UCDP Dyadic 25.1" },
    @{ file="ucdp-nonstate-251-csv.zip";   folder="ucdp-nonstate-251-csv";   label="UCDP Non-state 25.1" },
    @{ file="ucdp-onesided-251-csv.zip";   folder="ucdp-onesided-251-csv";   label="UCDP One-sided 25.1" },
    @{ file="ucdp-brd-dyadic-251-csv.zip"; folder="ucdp-brd-dyadic-251-csv"; label="UCDP BRD Dyadic 25.1" },
    @{ file="ucdp-prio-acd-251-csv_1.zip"; folder="ucdp-prio-acd-251-csv";   label="UCDP PRIO ACD 25.1" },
    @{ file="ucdp-actor-251-csv.zip";      folder="ucdp-actor-251-csv";      label="UCDP Actor 25.1" },
    @{ file="organizedviolencecy-251-csv_1.zip"; folder="organizedviolencecy-251-csv"; label="UCDP Organised Violence 25.1" }
)

foreach ($z in $zips) {
    $zipPath = "$DataDir\$($z.file)"
    $folderPath = "$DataDir\$($z.folder)"
    Get-File $z.file $zipPath $z.label
    Expand-Zip $zipPath $folderPath $z.label
}

# Flat CSV/XLSX datasets
$flat = @(
    @{ file="par.csv";                          label="PAR dataset" },
    @{ file="ucdp-candidate-csv.csv";           label="UCDP Candidate" },
    @{ file="ucdp_issues_dataset_dyadyear_232.csv"; label="UCDP Issues" },
    @{ file="CACE_1989-2017.xlsx";              label="CACE 1989-2017" },
    @{ file="ucdp-peace-agreements-221.xlsx";   label="UCDP Peace Agreements" },
    @{ file="un_votes_clean.xlsx";              label="UN votes (clean, 59 MB)" }
)

foreach ($f in $flat) {
    Get-File $f.file "$DataDir\$($f.file)" $f.label
}

Write-Host "`nAll datasets ready. Policy Stance builds its cache on first start (~8 min)."
