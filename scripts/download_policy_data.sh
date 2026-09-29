#!/usr/bin/env bash
# Download ALL Policy Stance datasets + pre-built cache from GitHub release.
# Safe to re-run: skips files/folders that already exist.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/services/policy_stance/data"
CACHE="$ROOT/services/policy_stance/outputs"
BASE="https://github.com/Takshak-CS/team128-geopolitical-intelligence/releases/download/policy-data-v1"
mkdir -p "$DATA" "$CACHE"

get() {
    local name="$1" dest="$2" label="$3"
    if [ -e "$dest" ]; then echo "  [skip] $label"; return; fi
    echo "  [download] $label ..."
    curl -fL --retry 3 -o "$dest" "$BASE/$name"
    echo "  [ok] $label"
}

unzip_to() {
    local zip="$1" dir="$2" label="$3"
    if [ -d "$dir" ]; then echo "  [skip] $label (already extracted)"; rm -f "$zip"; return; fi
    echo "  [unzip] $label ..."
    unzip -q "$zip" -d "$DATA"
    rm -f "$zip"
}

echo ""
echo "Policy Stance datasets -> $DATA"
echo ""

# UN GA voting
get "2025_7_23_ga_voting.xlsx" "$DATA/2025_7_23_ga_voting.xlsx" "UN GA voting 1989-2025 (70 MB)"

# UCDP zip datasets
declare -A ZIPS=(
    ["ged251-csv.zip"]="ged251-csv"
    ["ucdp-dyadic-251-csv_1.zip"]="ucdp-dyadic-251-csv"
    ["ucdp-nonstate-251-csv.zip"]="ucdp-nonstate-251-csv"
    ["ucdp-onesided-251-csv.zip"]="ucdp-onesided-251-csv"
    ["ucdp-brd-dyadic-251-csv.zip"]="ucdp-brd-dyadic-251-csv"
    ["ucdp-prio-acd-251-csv_1.zip"]="ucdp-prio-acd-251-csv"
    ["ucdp-actor-251-csv.zip"]="ucdp-actor-251-csv"
    ["organizedviolencecy-251-csv_1.zip"]="organizedviolencecy-251-csv"
)
for file in "${!ZIPS[@]}"; do
    folder="${ZIPS[$file]}"
    get "$file" "$DATA/$file" "$file"
    unzip_to "$DATA/$file" "$DATA/$folder" "$folder"
done

# Flat files
for f in par.csv ucdp-candidate-csv.csv ucdp_issues_dataset_dyadyear_232.csv CACE_1989-2017.xlsx ucdp-peace-agreements-221.xlsx un_votes_clean.xlsx; do
    get "$f" "$DATA/$f" "$f"
done

# Pre-built cache (skips the 8-minute first-run build)
echo ""
echo "Policy Stance cache -> $CACHE"
for z in cache_master_df.zip cache_runtime.zip; do
    dest_name="${z%.zip}"        # cache_master_df / cache_runtime
    pkl_name="${dest_name#cache_}.pkl"  # master_df.pkl / runtime.pkl -> wrong
    # Correct mapping
    case "$z" in
        cache_master_df.zip)  pkl="master_df.pkl" ;;
        cache_runtime.zip)    pkl="runtime_cache.pkl" ;;
    esac
    if [ -f "$CACHE/$pkl" ]; then echo "  [skip] $pkl (cache already present)"; continue; fi
    get "$z" "$CACHE/$z" "$z"
    echo "  [unzip] $pkl ..."
    unzip -q "$CACHE/$z" -d "$CACHE"
    rm -f "$CACHE/$z"
done

echo ""
echo "All datasets ready. Policy Stance will start instantly (cache preloaded)."
