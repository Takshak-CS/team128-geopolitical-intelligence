# Module notes: what integration found, and what was patched

Integration exercised all four modules together, against real data, for the
first time. That surfaced defects that each module's own dashboard did not
show. They fall into two groups:

- **Patched here.** Needed for the system to run or to be correct. Each is a
  few lines, kept in `patches/<module>.patch`, and marked
  `Team 128 integration fix` in the code. **Owners: please upstream these to
  your repos**, then run `python scripts/sync_modules.py pull <module>`.
- **Reported, not patched.** Methodology questions that belong to the module
  owner. The orchestrator works around them visibly (caveats, adjusted
  confidence) rather than hiding them.

## Soft Power Index (Anushree)

**Patched**
- `dash/backend/app/main.py`: the SQLAlchemy engine was created even with
  `DATA_SOURCE=files`, which imports `psycopg2`. Without it, files mode (the
  documented quick start) crashed at import. The engine is now skipped in
  files mode.

**Reported**
- **The model's largest SHAP feature is its own target.** In
  `output/shap_global.csv`, `score_roll3_mean` (the 3-year rolling mean of the
  soft-power score) has mean |SHAP| 9.63. The next feature, `property_rights`,
  has 0.66. `year_norm` is also in the top 10. The XGBoost R² of 0.966 is
  therefore mostly persistence, and the headline accuracy should be stated
  that way in the report. The orchestrator lists only indicator drivers and
  reports the share of attribution the lagged-score and time terms carry.
- Kalman 95% intervals are not clipped to the 0-100 scale. Monaco, ranked #1,
  has an interval of 81.2-108.1. The orchestrator turns interval width into
  confidence, so such scores carry low confidence.
- The module's own `dash/backend/Dockerfile` copies only `dash/backend`, but
  files mode reads `../../output`. The image cannot serve data. It is replaced
  by `deploy/soft_power.Dockerfile`, which keeps the layout.

## Policy Stance (Santhosh)

**Patched**
- `backend/codebook_parser.py`: **the Gleditsch-Ward table labelled several
  countries wrongly**, so UCDP conflict data was attributed to the wrong
  country:

  | GW code | Module's label | Correct country |
  |---|---|---|
  | 483 / 484 | Congo / DRC | Chad / Republic of the Congo |
  | 490 | Uganda | DR Congo |
  | 500 | Rwanda | Uganda |
  | 501 | Burundi | Kenya |
  | 510 | Ethiopia | Tanzania |
  | 520 | Eritrea | Somalia |
  | 530 | Somalia | Ethiopia |
  | 531 | Somaliland | Eritrea |
  | 701 / 702 / 703 | Tajikistan / Kyrgyzstan / Turkmenistan | Turkmenistan / Tajikistan / Kyrgyzstan |
  | 711 / 712 | Mongolia / Tibet | Tibet / Mongolia |
  | 341 / 347 / 349 | Kosovo / Serbia / Montenegro | Montenegro / Kosovo / Slovenia |
  | 990 | Nauru | Samoa |

  Codes 501 and 516 were both labelled "Burundi". Profiles are keyed by name,
  so one country's profile silently overwrote the other's. Kenya, Tanzania,
  Chad and Moldova had no entry at all. The fix is an `update()` block after
  the original table.
- `backend/data_loader.py`, **ISO3 → GW mapping**: it covered about 85
  countries. Every other UN member's votes fell through to a synthetic code,
  which removes them from profiles and blocs. The mapping now covers 202
  codes, including the legacy codes in 1989-1992 votes (`SUN`, `YUG`, `DDR`,
  `ZAR`, `GER`, `SCG`, ...). Germany now maps to GW 260 in both the vote data
  and the UCDP data. Before, votes used 255 and conflicts used 260, which
  split Germany into two entities.
- `backend/data_loader.py`, **the UN voting file was silently skipped**. The
  streaming xlsx reader looked for a column named `vote`, but the UN Digital
  Library export `2025_7_23_ga_voting.xlsx` names it `ms_vote`. The CSV path
  already handled `ms_vote`. The vote list stayed empty, the frame could not
  be built, and the loader's catch-all skipped the file. **No UN votes were
  loaded, so every bloc came from hand-written fallback rules.** After the
  fix, 544,453 votes load for 198 countries.
- `requirements.txt`: added `matplotlib`, `seaborn`, `scipy` and
  `python-louvain`. The code imports all four, but they were not listed.

**Reported**
- **The module's own model places India with China; the "Non-Aligned" label is
  hard-coded.** `/compare-insight` reads the model's bloc assignment before
  `MANUAL_OVERRIDES` is applied. With the UN votes loaded, it places India in
  the **China-Centered Bloc**: 70% vote match with China on sampled
  resolutions, 85.8% early and 72.3% recent agreement. That holds even though
  India is one of the anchors that *define* Non-Aligned. `/alliance-blocs` and
  `/blocs-by-year` then overwrite this with Non-Aligned. The Review 1 claim
  that "trade says China bloc, UN voting says Non-Aligned" is therefore
  produced by the override. The module's model agrees with Trade. The
  orchestrator fuses the model's placement, shows the published label next to
  it, and caveats the finding: its basis is the full 1989-2025 history, not
  the aligned year. Sri Lanka is overridden the same way (published
  China-Centered, model Russia+Allies). These results were computed without
  PyTorch, on the module's fallback embedding; with PyTorch Geometric
  installed the GAT path may place countries differently.
- **Alliance blocs are not discovered.** They are assigned by cosine
  similarity to the centroid of hand-picked *anchor* countries per bloc.
  India is itself an anchor of "Non-Aligned", and `MANUAL_OVERRIDES` pins
  India to Non-Aligned and Sri Lanka to China-Centered. Countries without
  votes fall to hand-written `FALLBACK_RULES`, or to the default
  "Non-Aligned". The Review deck says the blocs emerge "without being
  labelled" by Louvain; the code does not do that. The headline "India:
  trade says China bloc, diplomacy says Non-Aligned" therefore rests, on the
  diplomatic side, on an input rather than a finding. The orchestrator labels
  every bloc with its provenance (`vote_model`, `override_replaced`, `anchor`,
  `manual_override`, `fallback_rule`), lowers confidence accordingly, and attaches a caveat to
  any divergence built on it.
- `country_profiles[...].total_conflicts` / `total_deaths` disagree with the
  same profile's `timeline`: India shows 1 and 0, while its timeline sums to
  664 records and 59,215 deaths. The orchestrator uses the timeline.
- Timeline totals sum rows across all loaded UCDP datasets, so a conflict
  that appears in both the dyadic and GED data is counted twice.
- The runtime cache is considered fresh when it is newer than the input
  files. Changing loader code does not invalidate it; delete `outputs/`
  after a loader change.
- Profiles exist only for countries that appear as graph nodes: 111 before the
  vote fix (conflict data only) and 185 after it.
- The one-time pipeline build with the UN votes took about 8 minutes on the
  development machine. Most of it is parsing the xlsx and `_vote_pair_stats`
  in `graph_builder.py`, which loops in Python over every voter pair of every
  resolution. A vectorised version would be far faster.

## Trade Intelligence (Takshak)

The module already emits the shared envelope and has `/health` and
`/capabilities`. Its 125 tests pass in the platform virtualenv (pandas 2.3.3,
numpy 2.5.3).

**Patched**
- `frontend/index.html`: the dashboard hard-codes `127.0.0.1:8000/query`,
  which is now the orchestrator's port. It now accepts `?api=http://host:port`,
  and the briefing UI's drill-through link opens it as
  `http://localhost:8080/?api=http://127.0.0.1:8103`.
- `agent/trade_agent.py`: forecast claims read "indicates an stable trend";
  the article now matches the word.

**Reported**
- The module appends its confidence reason to the end of each `claim`. The
  adapter strips that suffix because the envelope already carries it in
  `reason`.

## Event Summarization (Shreyas)

Vendored at `3f026ed` (synced from `3e6579e`). That update added the module's
own validation of its KMeans themes (`cluster_quality` in `/analyze`), the
`/article-context` and `/article-relevance` endpoints, and "Domestic event
within X" wording for events with the same actor on both sides. The
integration patch below re-applied without conflicts.

**Patched**
- `src/api.py` and `src/preprocess.py`: **missing GDELT country codes became
  a partner called "NAN"**. `preprocess()` upper-cases the code columns with
  `astype(str)`, which turns NaN into the string `"NAN"`. For India on
  2026-09-22, 777 of 867 events were attributed to a partner "NAN", and the
  narration read "Key partners: NAN, India, United States". Both partner
  aggregations now drop the placeholder. A blanket NaN fix was avoided because
  `get_top5_events` groups on these columns, and `groupby` would silently drop
  the rows.
- `requirements.txt` described the Streamlit prototype. It had no fastapi or
  uvicorn, and missed `gTTS`, `Pillow` and `python-dotenv`, which
  `src/api.py` imports at startup. It is replaced with the backend's real
  dependencies.

**Reported**
- The domestic/international split counts an event as domestic only when
  *both* actors carry the country's code. Events whose counterpart GDELT left
  uncoded (most of them) are counted as international: India shows 23
  domestic and 844 international on 2026-09-22, although most of those are
  state-level Indian politics. The orchestrator quotes the split as its own
  claim (`event_domestic_split`), at confidence 0.4 or lower, with a caveat
  saying the domestic count is a floor rather than an estimate.
- **The theme validation describes a different clustering from the themes
  shown.** Production KMeans uses k=4, but two of the four clusters receive the
  same theme name. `cluster_counts` therefore lists three themes (China, India
  and Iran on 2026-09-22 and Iran on 2026-09-28 all show this). The reported
  silhouette (for example 0.54 for Iran on 2026-09-28) scores the 4-cluster
  fit. The module's own `k_sweep` rates k=2 best (`best_k`: 2) in every
  case. The orchestrator states the validation as the module reports it. Fixing
  this belongs in the module: choose k from the sweep, or validate the named
  themes.
- `/article-relevance` returns `unavailable` for sites that refuse non-browser
  fetches (HTTP 403). On 2026-09-28 `northbaynipissing.com` always refused.
  `krcgtv.com` refused on some attempts and served the page on others. The
  orchestrator falls back to the URL slug in that case (see below).
- The country list (`src/utils.py COUNTRY_MAP`) covers about 150 countries.
  GDELT codes outside it still work in `/analyze`, but display as the raw
  code.
- `data.gdeltproject.org` now redirects HTTP to HTTPS. `requests` follows the
  redirect, but `GDELT_BASE_URL` should use `https://`.
- The day's export is published around 10:00 UTC the next day. Before that,
  "yesterday" returns 404. The orchestrator retries the previous day.

**What the orchestrator now uses from this module, and why**

Before this change the Events adapter turned `/analyze` into three claims: the
day's activity, the top counterparts, and the single top event, which was
quoted unchecked. Trade contributes up to six claims to a country question.
This module's distinctive output never reached the briefing:

- the theme validation, which was dropped
- the domestic split, which was held back
- a check on whether an event is mis-tagged, which was never made
- the GGE baseline, fetched for only one partner

The top event could be plainly wrong. For Iran on 2026-09-28, event #3,
"Israel vs Iran, Fight, Goldstein -10", came from an article titled "Ontario
gas price prediction for Sept. 30".

The adapter now makes up to ten claims per country and day
(docs/CONTRACT.md, "Events claims"):

- `event_themes`: the themes, stated with the module's cluster validation.
- `event_domestic_split`: the split, with its caveat attached.
- `event_headline` × 3: each top event is checked against its source article
  with `/article-relevance`, which uses no AI model. Gemini `/enrich-event`
  is not used, so it needs no key and spends no quota. When the site refuses
  the fetch, the adapter checks whether the URL slug names either country. An
  event the source does not support is reported as "Likely mis-tagged by
  GDELT" at confidence 0.15-0.2, not as news.
- `relationship_baseline` × 3: GGE baselines for the three most active
  counterparts, each next to today's figures for that pair. Fusion's
  "out of character" check now has three pairs to test instead of one.
- `event_activity` also reports the share of events the country initiated and
  carries `tone_counts`.

The briefing UI gives every agent the same panel: KPI tiles, views drawn from
the claims' evidence, every claim with its confidence and caveat, and the raw
calls. Previously each agent got only a numbered list of claim sentences. The
Events panel shows themes with their cluster quality, the domestic split, the
checked headlines with verification badges, and a counterparts table that
puts today's Goldstein next to the 1990-2024 baseline and its trend line.

## CAMEO codes (verified)

Checked against the GDELT V1 export for 2026-09-22 (207 distinct codes):
Timor-Leste is coded `TMP` (16 events), not `TLS`. `COD`, `MMR`, `PSE`, `SRB`,
`SSD`, `TWN` and `DEU` appear as their ISO3. Romania appeared under neither
`ROU` nor `ROM` that day; the orchestrator uses `ROM` per the CAMEO manual.
