# Data each service needs

No large dataset is committed. Every data directory below is gitignored.
Everything is public; sources are listed so the system can be rebuilt from
nothing.

| Service | Put it here | What | Source | Size |
|---|---|---|---|---|
| Soft Power | `services/soft_power/output/` | model artifacts (panel, Kalman results, SHAP, embeddings) | **committed upstream**, nothing to do | 69 MB |
| Trade | `services/trade_intelligence/cache/` | parquet cache built from CEPII BACI HS92 V202601 | build with `python scripts/build_cache.py` from the 30 yearly BACI CSVs (8.2 GB, cepii.fr), or copy an existing `cache/` | 21 MB |
| Policy Stance | `services/policy_stance/data/` | `2025_7_23_ga_voting.xlsx` (UN GA voting) | UN Digital Library, record 4060887 | 74 MB |
| | | `ucdp-prio-acd-251-csv.zip`, `ucdp-dyadic-251-csv.zip`, `ucdp-brd-dyadic-251-csv.zip`, `ucdp-nonstate-251-csv.zip`, `ucdp-onesided-251-csv.zip`, `ged251-csv.zip` | `https://ucdp.uu.se/downloads/` (UCDP 25.1) | 29.6 MB |
| Events | `services/event_summarization/data/` | `dyad_geopolitical_scores.csv` (GGE 1990-2024 baseline) | unzip `Geopolitical_Scores/dyad_geopolitical_scores.zip` from github.com/tianyufan-econ/global-geopolitics | 97 MB |
| | | GDELT V1 daily exports | downloaded automatically on first use of a date; the module keeps the last 5 | ~50 MB per day |

## Notes

- **Policy Stance** discovers any file under its folder whose name matches a
  known dataset and builds a runtime cache in `outputs/` on first start. That
  takes several minutes with the UN votes. The cache is reused while it is
  newer than the input files, so **delete `outputs/` after changing loader
  code or replacing a dataset with an older file.**
- Without the UN voting file, Policy Stance still runs on UCDP alone, but
  every bloc then comes from hand-written rules. The orchestrator labels
  those `fallback_rule` and lowers their confidence.
- Without the GGE file, Events still answers; the orchestrator notes that the
  1990-2024 baseline is unavailable.
- **Events article verification** (`/enrich-event`, `/briefing`) needs
  `GEMINI_API_KEY`. The orchestrator does not use those endpoints.
