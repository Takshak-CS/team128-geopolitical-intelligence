#!/usr/bin/env bash
# Download ALL Policy Stance datasets + pre-built cache from GitHub release.
# Safe to re-run: skips files/folders that already exist.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/services/policy_stance/data"
CACHE="$ROOT/services/policy_stance/outputs"
BASE="https://github.com/Takshak-CS/team128-geopolitical-intelligence/releases/download/policy-data-v1"
mkdir -p "$DATA" "$CACHE"

# Clear stale cache so the module rebuilds from freshly downloaded data
rm -f "$CACHE"/*.pkl "$CACHE/runtime_manifest.json" 2>/dev/null || true

get() {
    local name="$1" dest="$2" label="$3"
    if [ -e "$dest" ]; then echo "  [skip] $label"; return; fi
    echo "  [download] $label ..."
    curl -fL --retry 3 -o "$dest" "$BASE/$name"
    echo "  [ok] $label"
}

echo ""
echo "Policy Stance datasets -> $DATA"
echo ""

# UN GA voting
get "2025_7_23_ga_voting.xlsx" "$DATA/2025_7_23_ga_voting.xlsx" "UN GA voting 1989-2025 (70 MB)"

# UCDP zip datasets
for entry in \
    "ged251-csv.zip|ged251-csv" \
    "ucdp-dyadic-251-csv_1.zip|ucdp-dyadic-251-csv" \
    "ucdp-nonstate-251-csv.zip|ucdp-nonstate-251-csv" \
    "ucdp-onesided-251-csv.zip|ucdp-onesided-251-csv" \
    "ucdp-brd-dyadic-251-csv.zip|ucdp-brd-dyadic-251-csv" \
    "ucdp-prio-acd-251-csv_1.zip|ucdp-prio-acd-251-csv" \
    "ucdp-actor-251-csv.zip|ucdp-actor-251-csv" \
    "organizedviolencecy-251-csv_1.zip|organizedviolencecy-251-csv"
do
    file="${entry%%|*}"
    folder="${entry##*|}"
    if [ -d "$DATA/$folder" ]; then echo "  [skip] $folder"; continue; fi
    get "$file" "$DATA/$file" "$file"
    echo "  [unzip] $folder ..."
    unzip -q "$DATA/$file" -d "$DATA"
    rm -f "$DATA/$file"
done

# Flat files
for f in par.csv ucdp-candidate-csv.csv ucdp_issues_dataset_dyadyear_232.csv CACE_1989-2017.xlsx ucdp-peace-agreements-221.xlsx un_votes_clean.xlsx; do
    get "$f" "$DATA/$f" "$f"
done

echo ""
echo "All datasets ready. Policy Stance builds its cache on first start (~8 min)."
