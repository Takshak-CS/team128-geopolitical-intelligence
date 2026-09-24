# Integration plan: orchestration layer

This is the plan evaluated before building the orchestration layer, and the
decisions it led to. The architecture follows the Phase 3 diagram: four
analysis agents feed an insight-fusion agent through an orchestrator, and the
orchestrator answers the user.

## 1. What the four modules actually expose

Surveyed from the code at the commits pinned in `modules.lock.json`, not from
the slides.

| Agent | Owner | Native API | Country key | Time grain | Output shape |
|---|---|---|---|---|---|
| Soft Power | Anushree | `GET /api/latest`, `/api/timeseries`, `/api/drivers/{iso3}`, `/api/forecast/{iso3}`, `/api/peers/{iso3}` | ISO3 | annual 2000-2024 | lists of rows; Kalman 95% intervals, no per-claim confidence |
| Policy Stance | Santhosh | `GET /status`, `/countries`, `/country/{name}`, `/alliance-blocs`, `/blocs-by-year/{y}`, `/compare-insight`, `/forecast` | its own display names over Gleditsch-Ward codes | annual 1989-2025 | nested profile dicts; no confidence |
| Trade | Takshak | `POST /query` (6 query types), `GET /graph`, `/health`, `/capabilities` | ISO3 / BACI names | annual 1995-2024 | **the shared envelope** |
| Events | Shreyas | `POST /analyze`, `GET /historical-context`, `WS /ws/pipeline` | CAMEO actor codes | daily (GDELT V1) | analysis dict; no confidence |

All four default to port 8000, and only Trade speaks the shared contract.

## 2. Options considered

**Transport.** In-process imports vs HTTP. The four modules have conflicting
dependency pins (Policy pins `torch==2.8`, Events wants Python 3.12, Trade
pins pandas 2.3.2), keep module-level global state, and resolve data paths
relative to their own working directory. Importing them into one process
would mean rewriting all four. **Decision: HTTP.** Each module runs unchanged
as its own service; the orchestrator is the only new process.

**Where normalisation lives.** Ask each owner to add a `/agent/query`
endpoint that emits the envelope, or translate in the orchestrator. The
first spreads the contract across four codebases and four owners' schedules.
**Decision: one adapter per agent inside the orchestrator** (`app/agents/`).
Owners keep their APIs; the contract is enforced in one place and tested
there.

**Intent parsing.** An LLM parser vs rules. An LLM parser needs a key and
network in the demo, and its choices cannot be unit-tested. **Decision:
rule-based parser** with a country gazetteer; every choice appears in the
plan (`POST /parse` shows it without calling any agent). An LLM parser can
be added later behind the same `QueryPlan` interface.

**Codebase shape.** Git submodules vs a monorepo. Submodules break for anyone
who clones without `--recursive`, and the modules needed small fixes to run
together. **Decision: vendor each module into `services/<name>/` at a pinned
commit**, keep the fixes as reviewable patches in `patches/`, and provide
`scripts/sync_modules.py` to pull an owner's newer commit and re-apply them.

## 3. The three alignment problems

**Identity.** One crosswalk, `orchestrator/app/countries.py`, maps ISO3 to
and from Gleditsch-Ward codes (Policy), CAMEO codes (Events: `TMP` for
Timor-Leste, for example), and names, aliases and demonyms (for questions).
The Policy adapter never trusts a name across the boundary. It maps ISO3 to a
GW code, then asks the module which name it uses for that code.

**Time.** For "latest" questions the orchestrator reads each annual agent's
newest year (Trade from `/capabilities`, Soft Power from its leaderboard,
Policy's configured 2025) and aligns on the **newest year all selected agents
can serve**, which is 2024. It passes that year to Trade and to Policy's
`/blocs-by-year`. Events stays daily and uses the latest published GDELT day,
falling back a day when the export is not out yet. Where it can, it sets that
day against the GGE 1990-2024 annual baseline for the same pair. A request
for a year outside an agent's coverage produces a warning, and a historical
year drops Events from the plan.

**Trust.** Every insight carries `confidence` and `reason`. For agents that
publish uncertainty but no confidence, the adapter derives one from what the
module does publish and records how in `evidence.confidence_basis`: Soft
Power from its Kalman interval width, Events from event volume (capped at 0.7
for GDELT coding noise), Policy from where each bloc assignment came from.

## 4. Fusion design

1. Normalise all four responses to the envelope and validate them. Contract
   violations are reported, not fatal.
2. Deduplicate on (agent, entity, facet, sector, pair) and keep the most
   confident claim.
3. Cross-check with explicit rules over independent agents:
   - trade bloc anchor vs UN bloc (the India question from the deck)
   - most critical trade partner and dominant sector supplier vs UN bloc
   - soft-power trajectory vs trade forecast
   - today's GDELT tone with the critical partner vs trade dependence, and vs
     the GGE baseline
   - bilateral: shared trade bloc vs shared UN bloc, dependence vs vote agreement
   - shock: which diplomatic camps the most-exposed economies sit in
4. Score it. When independent agents support the *same* proposition (both
   measure alignment with one country, or both measure momentum), the finding
   gets `1 - prod(1 - c_i)`. When it joins two *different* facts ("coverage
   is cooperative" and "the partner carries 12% of trade"), it gets
   `min(c_i)`. A divergence also gets `min(c_i)`. Divergences rank first:
   they are the project's core analytical claim, not noise to average away.
5. Write the briefing. Every sentence comes from a finding, and every finding
   cites its agents and confidence.

## 5. Degradation

Agents are called in parallel with per-agent timeouts (Events gets 120 s
because its first request for a day downloads the GDELT export). An agent
that is down, still loading, slow, or failing gets a status (`unavailable`,
`not_ready`, `timeout`, `error`) and the briefing is built from the rest.
The coverage line in the briefing always says which agents answered.

## 6. What had to change in the modules

Kept deliberately small. Every change is in `patches/`, with its reason
in `docs/MODULE_NOTES.md`. Nothing about any module's methodology was
changed. The patches fix defects that stopped a module from starting, from
loading its own data, or from reporting the right country.

## 7. Delivery checklist (Gantt items from Review 1)

| Item | Status |
|---|---|
| Freeze shared envelope + ISO3 crosswalk | done: `app/contract.py`, `app/countries.py`, `docs/CONTRACT.md` |
| Orchestrator: intent parsing + parallel fan-out | done: `app/intent.py`, `app/pipeline.py` |
| Insight fusion: dedupe, corroborate, confidence rank | done: `app/fusion.py`, `app/briefing.py` |
| Unified briefing UI | done: `orchestrator/static/index.html`, with drill-through links to each module dashboard |
| End-to-end evaluation + case studies | harness in `scripts/smoke_test.py`; case-study review against published analysis remains |
| Deployment: one-command Docker Compose | `docker-compose.yml` (config validated; images not yet built on this machine) |
