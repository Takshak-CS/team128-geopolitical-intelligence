# Data each service needs

No large dataset is committed. Every data directory below is gitignored
except the trade cache, which is small enough to commit.
Everything is public; sources are listed so the system can be rebuilt from
nothing.

| Service | Put it here | What | Source | Size |
|---|---|---|---|---|
| Soft Power | `services/soft_power/output/` | model artifacts (panel, Kalman results, SHAP, embeddings) | **committed upstream**, nothing to do | 69 MB |
| Trade | `services/trade_intelligence/cache/` | parquet cache built from CEPII BACI HS92 V202601 (1995-2024, 4 sectors, 234 countries, World Bank GDP/population) | **committed**, nothing to do. To rebuild (new BACI release): `python scripts/build_cache.py` from the 30 yearly BACI CSVs (8.2 GB, cepii.fr) in the trade repo, commit `cache/` there, then copy it here | 21 MB |
| Policy Stance | `services/policy_stance/data/` | `2025_7_23_ga_voting.xlsx` (UN GA voting) | UN Digital Library, record 4060887 | 74 MB |
| | | `ucdp-prio-acd-251-csv.zip`, `ucdp-dyadic-251-csv.zip`, `ucdp-brd-dyadic-251-csv.zip`, `ucdp-nonstate-251-csv.zip`, `ucdp-onesided-251-csv.zip`, `ged251-csv.zip` | `https://ucdp.uu.se/downloads/` (UCDP 25.1) | 29.6 MB |
| Events | `services/event_summarization/data/` | `dyad_geopolitical_scores.csv` (GGE 1990-2024 baseline) | unzip `Geopolitical_Scores/dyad_geopolitical_scores.zip` from github.com/tianyufan-econ/global-geopolitics | 97 MB |
| | | GDELT V1 daily exports | downloaded automatically on first use of a date; the module keeps the last 5 | ~50 MB per day |

## Setting up Policy Stance datasets (for all team members)

Policy Stance discovers any file **anywhere under `services/policy_stance/`**
whose name matches a known dataset. The simplest setup:

```
services/policy_stance/data/
    2025_7_23_ga_voting.xlsx        ← UN Digital Library export (74 MB)
    ucdp-dyadic-251-csv/
        Dyadic_v25_1.csv
    ged251-csv/
        GEDEvent_v25_1.csv
    ucdp-nonstate-251-csv/
        NonState_v25_1.csv
    ucdp-onesided-251-csv/
        OneSided_v25_1.csv
    ucdp-brd-dyadic-251-csv/
        BattleDeaths_v25_1.csv
```

Download sources:
- **UN votes** — https://digitallibrary.un.org/record/4060887 → Export → Excel
- **UCDP 25.1** — https://ucdp.uu.se/downloads/ → download the five datasets above as zip, unzip into `data/`

After placing files, start the module. On first run it builds a cache in
`services/policy_stance/outputs/` (takes ~8 minutes; 544,453 votes load).
Subsequent starts use the cache and are ready in under a minute.

**Without the UN voting file** Policy Stance still runs on UCDP conflict data
alone, but every bloc assignment comes from hand-written fallback rules and the
orchestrator labels those `fallback_rule` with lowered confidence.

**Santhosh's shortcut (Windows):** If you already have the files elsewhere,
create a directory junction instead of copying:
```powershell
cmd /c mklink /J services\policy_stance\datasets "C:\path\to\your\DATASETS"
```

## Notes

- **Policy Stance** builds a runtime cache in `outputs/` on first start.
  The cache is reused while it is newer than the input files.
  **Delete `outputs/` after changing loader code or swapping a dataset.**
- Without the GGE file, Events still answers; the orchestrator notes the
  1990-2024 baseline is unavailable.
- **Events article verification** needs `GEMINI_API_KEY`. The orchestrator
  does not use those endpoints.
