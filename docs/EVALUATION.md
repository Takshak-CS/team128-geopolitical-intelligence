# Evaluation: query understanding and answer quality

This is how the system is measured before and after a change to how questions
are understood, for example query reformulation. The benchmark lives in
`orchestrator/evaluation/`.

| File | What it is |
|---|---|
| `questions.json` | the labelled question set |
| `metrics.py` | the metric definitions, as code (unit-tested in `tests/test_evaluation.py`) |
| `run.py` | runs the set, prints the report, saves or compares results |
| `results/*.json` | saved reports: `baseline_*` before query reformulation, `reformulated_*` after it (`*_parser` offline, `*_live` against the running system) |

## The question set

The set has **18 groups and 90 questions**. A group is one question asked
several ways. Every question in a group shares the group's gold label, which
holds the plan the system should make:

- intent
- countries (ISO3)
- time window
- sector
- shock severity
- forecast metric
- trade ranking query
- agents to ask

The label also lists the **facets** an answer needs. For example, a forecast
question needs `trade_outlook`.

Each question has a `kind`, which says how it differs from its group's original:

| kind | Example |
|---|---|
| `original` | How exposed is India right now? |
| `reworded` | How vulnerable is India at the moment? |
| `alias` | How vulnerable is Bharat at the moment? (capital, endonym, abbreviation) |
| `typo` | Indai exposure |
| `casual` | give me the overall picture on india |
| `numeric` | What if Russia halves its oil and gas exports? (numbers in words, relative years) |

**Splits.** 12 groups are `dev` and 6 are `test`. Build and tune reformulation
by looking at `dev` only. Report `test` as the held-out result. A method tuned
on the questions it is scored on will look better than it is. The runner lists
missed plans for `dev` only by default for that reason.

**Reference date.** Relative times ("yesterday", "in five years") are resolved
against the set's `reference_date` (2026-10-26), so parser scores are the same on
any day.

**Rules for changing the set.**
- Never edit a gold label to match what the system outputs. A gold label says
  what the right plan is.
- To add questions, add them and bump `version`. Re-run the baseline on the
  new version before comparing.
- Question types the system does not support (for example three-country
  comparisons) are left out, not labelled with a plan the system cannot make.

## Running it

```powershell
cd orchestrator
..\.venv\Scripts\python -m evaluation.run                           # parser metrics, offline, seconds
..\.venv\Scripts\python -m evaluation.run --live                    # also ask the running system (scripts\run_all.ps1 first)
..\.venv\Scripts\python -m evaluation.run --save after_reform       # save a report
..\.venv\Scripts\python -m evaluation.run --compare evaluation\results\baseline_parser.json
..\.venv\Scripts\python -m evaluation.run --ablation                # what each reformulation step adds
..\.venv\Scripts\python -m evaluation.run --steps none              # the parser without reformulation
```

`--live` sends all 90 questions to `POST /ask` one at a time and adds the
answer metrics. Live answers depend on the data each agent has that day,
especially the GDELT day for Events. Compare a live run with a live run made
the same day, and a parser run with a parser run.

## Metrics

### Query understanding (offline)

| Metric | Definition | Why it matters |
|---|---|---|
| Intent accuracy | questions whose intent is right ÷ questions | The intent decides which agents are asked and which claims lead |
| Intent macro-F1 | F1 per intent, averaged with equal weight | Stops the common intents hiding a weak one |
| Entity precision / recall / F1 | over all ISO3 codes: precision = right codes found ÷ all codes found; recall = right codes found ÷ all codes expected | Recall drops when a country is missed (Bharat); precision drops when an extra one is picked |
| Subject accuracy | the plan's first country is the gold one (for bilateral, the first two in either order) | Answering about China when asked about Vietnam is worse than missing a sector |
| Fallback rate | questions that name a country but get no country in the plan ÷ questions that name a country | These get a "Global overview" instead of an answer |
| Slot accuracy | per slot (time, sector, severity, metric, trade query), over the questions whose gold sets that slot | Shows which part of parsing fails |
| Agent selection precision / recall | over the agent lists | Missing an agent loses its claims; an extra one adds noise |
| Plan exact match | every slot the gold sets is right | The strictest single number |
| **Paraphrase consistency** | rewordings whose plan equals their original's plan ÷ rewordings | The headline metric for reformulation: the same question should get the same answer however it is asked |
| Understanding confidence | the plan's `understanding` (docs/CONTRACT.md), averaged over all questions, over right plans and over wrong plans | A useful confidence is high on right plans and low on wrong ones |
| Understanding Brier | mean of (understanding − 1 if the plan is right, else 0)² | Calibration of that confidence; 0 is perfect, lower is better |

### Answers (`--live`)

| Metric | Definition | Why it matters |
|---|---|---|
| Agent answer rate | agents that returned claims ÷ agents asked, averaged over questions | A wrong plan often asks agents that have nothing to say |
| Facet recall | gold facets present in findings about the question's countries ÷ gold facets | Did the answer contain what the question asked for |
| Facet hit rate | questions with facet recall above 0 | Questions that got at least part of the right answer |
| Cross-agent findings / question | corroborations + divergences + cross-agent findings | The project's core output; a fallback plan usually produces none |
| Attribution rate | briefing claim lines that cite an agent and a confidence ÷ claim lines | Must stay 100%: nothing in the briefing may be unsourced |
| Top-5 mean confidence | mean confidence of the first five findings | **Descriptive only** (see below) |
| Latency p50 / p95 | per `/ask`, in ms | Reformulation adds a step; it must not make answers slow |

### What confidence does and does not measure

A claim's confidence comes from the data behind it:

- **Trade:** completeness, network connectivity and propagation steps.
- **Soft Power:** the width of the Kalman interval.
- **Policy Stance:** where the bloc label came from.
- **Events:** event volume, capped at 0.7.

docs/CONTRACT.md gives the formulas. Confidence does not measure whether the
question was understood, and nothing in it is calibrated against outcomes.

So reformulation cannot honestly raise the confidence of a claim. The same
plan gets the same data and the same confidence. What it can do is make the
question reach the plan that gets the strong, relevant claims instead of a
fallback.

Do not use mean confidence as a target. It can be gamed: a plan that drops
Events, whose claims are capped at 0.7, raises the mean while the answer gets
worse. Report it next to facet recall and cross-agent findings, never alone.

Checking that confidence is *calibrated* means checking that claims at 0.7 are
right about 70% of the time. That needs claims labelled right or wrong, which
this benchmark does not have. Places to get those labels:

- Trade forecasts: back-test on held-out years.
- Events headlines: label by hand.
- Soft Power: compare with external indices, which is already done.

The scores would then be expected calibration error and the Brier score.

## Baseline (before reformulation, 2026-10-26)

Rule-based parser at commit `08fcc90`. The live run used all four agents, with
caches warm (the first run of the day had p95 2.1 s).

| Metric | all | dev | test |
|---|---|---|---|
| Plan exact match | 67.8% | 69.6% | 64.7% |
| Paraphrase consistency | 59.7% | 62.2% | 55.6% |
| Intent accuracy | 72.2% | 75.0% | 67.6% |
| Entity F1 (precision 1.00) | 0.894 | 0.874 | 0.916 |
| Fallback rate | 16.4% | 22.7% | 6.9% |
| Facet recall (live) | 0.715 | 0.738 | 0.676 |
| Cross-agent findings / question (live) | 2.30 | 1.66 | 3.35 |
| Attribution rate (live) | 100% | 100% | 100% |
| Latency p50 / p95 (live) | 390 / 860 ms | | |

By kind, plan exact match is:

| Kind | Plan exact |
|---|---|
| original | 100% |
| reworded | 87.5% |
| casual | 76.9% |
| alias | 55.6% |
| numeric | 25.0% |
| typo | 7.7% |

Two of these fail often enough to lose the country altogether:

- **Typos** lose the country in 67% of cases.
- **Aliases** lose it in 22% of cases. The aliases that fail are Bharat, London, Deutschland, Hanoi, Berlin, Sino-, ROK.

Shock questions phrased without the trigger words ("reduces", "simulate a
drop", "cut in half") fall back to a country profile. Relative horizons ("in
five years", "next 5 years") are not read.

Facet recall averages 0.97 on originals, 0.66 on aliases and 0.15 on typos.
Agent answer rate is 100% everywhere: a fallback plan still gets answers, just
not to the question asked. That is why facet recall, not answer rate, shows the
damage.

One gap is not a parsing problem. "How dependent is Germany on Russian energy?"
parses correctly, but no `bilateral_trade_dependence` claim comes back. The
Trade agent's leverage query reports only each country's top dependencies, and
in 2024 Russia is not among Germany's top energy partners (Norway is). There is
no pairwise "share of A's energy from B" query, so the system never states the
number the question asks for.

## After query reformulation (2026-10-26)

Query reformulation (`app/reformulate.py`, described in docs/CONTRACT.md) runs
before the parser. It has four rule-based steps: aliases, spelling, numbers and
phrasing. The live runs were made on the same day with warm caches, all four
agents up.

| Metric | Baseline | Reformulated |
|---|---|---|
| Plan exact match (dev / test) | 69.6% / 64.7% | 100% / 100% |
| Paraphrase consistency (dev / test) | 62.2% / 55.6% | 100% / 100% |
| Intent accuracy | 72.2% | 100% |
| Entity F1 (precision stays 1.00) | 0.894 | 1.000 |
| Fallback rate | 16.4% | 0% |
| Understanding Brier | 0.195 | 0.013 |
| Facet recall (live) | 0.715 | 0.972 |
| Facet hit rate (live) | 76.7% | 100% |
| Cross-agent findings / question (live) | 2.30 | 2.38 |
| Attribution rate (live) | 100% | 100% |
| Top-5 mean confidence (live) | 0.718 | 0.708 |
| Latency p50 / p95 (live) | 390 / 860 ms | 393 / 802 ms |

The baseline Brier (0.195) uses the plan checks alone, with reformulation
switched off.

How to read it:

- **The plan improves; the claims do not get more confident.** Top-5 mean
  confidence is unchanged (0.718 → 0.708), as expected. The same plan gets the
  same data and the same claim confidence. What changed is that reworded
  questions now reach the plan that answers them: facet recall rose from 0.72
  to 0.97.
- **The new confidence is informative.** Understanding confidence is the
  system's estimate that it read the question correctly. Its Brier score fell
  from 0.195 to 0.013. A plan that falls back to a global overview without a
  ranking cue now scores 0.4 and the briefing warns about it, instead of
  answering with full confidence.
- **The remaining facet gap is a data gap, not a parsing one.** Germany-Russia
  energy dependence still lacks a `bilateral_trade_dependence` claim (see the
  baseline notes).
- **Cost.** Reformulation adds about 2 ms per question offline (0.05 ms →
  2.2 ms). Live latency is unchanged within noise.

Ablation (`--ablation`), plan exact match:

| Steps | dev | test | fallback (all) | Brier (all) |
|---|---|---|---|---|
| none (parser only) | 69.6% | 64.7% | 16.4% | 0.195 |
| only aliases | 78.6% | 70.6% | 9.6% | 0.162 |
| only spelling | 82.1% | 73.5% | 5.5% | 0.160 |
| only numbers | 69.6% | 73.5% | 16.4% | 0.162 |
| only phrasing | 80.4% | 73.5% | 16.4% | 0.099 |
| all but aliases | 91.1% | 91.2% | 5.5% | 0.041 |
| all but spelling | 89.3% | 88.2% | 9.6% | 0.041 |
| all but numbers | 100% | 91.2% | 0% | 0.046 |
| all but phrasing | 91.1% | 91.2% | 0% | 0.090 |
| all steps | 100% | 100% | 0% | 0.013 |

Every step contributes. Spelling removes the most fallbacks; phrasing does the
most for calibration. Numbers helps only the test split, because the dev split
has no relative-year questions.

### What these numbers do not show

**The test split is not blind.** The same person wrote the test questions and
the reformulation rules, after seeing which test questions failed. 100% on
`test` therefore shows the rules cover the phrasings in this set. It does not
show how they handle phrasings nobody anticipated.

For a held-out result that means something, ask someone who has not seen
`app/reformulate.py` to write new questions:

1. A teammate writes 30-50 questions in the same group format as
   `questions.json`, as version 2.
2. Run `--steps none` and `--steps all` on it.
3. Report those numbers as the generalisation result.

Expect them to be well below 100%. Rules cover only the aliases, misspellings
and phrasings they list.

**Questions the system does not support are not in the set.** For example,
"Is India closer to China or the US?" compares three countries. The bilateral
plan compares only the first two, and reformulation does not change that.

## Using it for further changes

1. Keep the `baseline_*` and `reformulated_*` reports as they are.
2. Build changes looking only at `dev` misses (`run.py` lists them), or at a
   new set.
3. Compare offline with `--compare`, and live against a run made the same day.
4. These should rise: paraphrase consistency, entity F1, intent accuracy and
   facet recall.
5. These should fall: fallback rate and understanding Brier.
6. These must hold:
   - originals at 100% plan exact, and no original rewritten (tests enforce
     both)
   - attribution at 100%
   - latency close to the baseline

With 34 test questions, one question moves a test-split rate by about 3
points. Read small differences as noise.
