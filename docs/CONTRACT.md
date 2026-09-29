# The shared contract

## Envelope

Every agent response, after its adapter, has this shape. It is the Trade
agent's native format, which the team adopted as the four-agent contract.

```json
{
  "agent": "trade_intelligence",
  "metadata": { "query_type": "...", "year": 2024, "sector": "all", "time_grain": "annual", "method": "...", "data_quality": {} },
  "insights": [
    {
      "entity_iso3": "IND",
      "entity_name": "India",
      "claim": "One self-contained, readable finding.",
      "score": 0.14,
      "confidence": 0.92,
      "reason": "What limited the confidence.",
      "evidence": { "the numbers the claim rests on": "..." },
      "facet": "trade_exposure",
      "caveat": "Optional. What the reader must know before relying on the claim."
    }
  ]
}
```

- `entity_iso3` is the join key. It is null only for non-country entities,
  such as a whole bloc.
- `confidence` (0-1) plus `reason` let fusion rank and cross-check claims
  rather than just concatenate them.
- `facet` is optional in the base contract and added by every adapter. It
  names what the insight is about, so fusion can line up claims from
  different agents about the same thing.
- `caveat` is optional. An adapter sets it when a claim is only safe to read
  with a qualification attached: a known bias in how the number is produced,
  or a check the claim failed. Fusion copies it onto the finding. The UI shows
  it under the claim, and the briefing markdown prints it on the line beneath.
  It stays with its claim and does not go into the page-level caveats, which
  are for cross-agent findings.
- `app.contract.validate_envelope` checks the required fields and the
  confidence range. Fusion reports violations under `fused.contract_issues`
  instead of failing.

## Facets by agent

| Agent | Facets | Native call(s) |
|---|---|---|
| Soft Power | `influence`, `influence_trend`, `influence_outlook`, `influence_drivers`, `influence_peers`, `bilateral_influence` | `/api/latest`, `/api/timeseries`, `/api/forecast/{iso3}`, `/api/drivers/{iso3}`, `/api/peers/{iso3}` |
| Policy Stance | `diplomatic_alignment`, `diplomatic_partners`, `conflict_exposure`, `conflict_outlook`, `bilateral_diplomacy`, `diplomatic_blocs` | `/status`, `/countries`, `/blocs-by-year/{y}` (or `/alliance-blocs`), `/country/{name}`, `/compare-insight`, `/forecast` |
| Trade | `trade_exposure` (risk), `trade_alignment` (blocs), `trade_dependence` (leverage), `supply_fragility`, `shock_impact`, `trade_outlook` (forecast), `bilateral_trade_bloc`, `bilateral_trade_dependence` | `POST /query`, `/capabilities` |
| Events | `event_activity`, `event_partners`, `event_themes`, `event_domestic_split`, `event_headline`, `bilateral_events`, `relationship_baseline` | `POST /analyze`, `/historical-context`, `/article-relevance` |

## Events claims

For one country and one GDELT day, the Events adapter makes up to ten claims.

| Facet | Count | Built from | What it says |
|---|---|---|---|
| `event_activity` | 1 | `/analyze` `metrics`, `event_type_counts`, `tone_counts` | event volume, mean Goldstein and tone, the share of conflictual and cooperative event types, the share the country initiated |
| `event_partners` | 1 | `/analyze` `partners` | the most active counterparts, each with its own mean Goldstein |
| `event_themes` | 1 | `/analyze` `cluster_counts`, `cluster_quality` | the KMeans themes as shares of the day, stated with the module's own validation of that clustering: silhouette against a shuffled-data baseline, and stability across seeds |
| `event_domestic_split` | 1 | `/analyze` `domestic`, `international` | domestic vs international counts and tone. Always carries a `caveat`: the module counts an event as domestic only when both actors carry the country's code, so events with an uncoded counterpart land in "international" and the domestic count is a floor |
| `event_headline` | 3 | `/analyze` `top5_events[:3]`, `/article-relevance` per event | each top event, checked against its source article (below) |
| `relationship_baseline` | up to 3 | `/historical-context` for the three most active counterparts (the named pair in a bilateral question) | the GGE 1990-2024 label, 10-year average and trend, next to today's count and Goldstein for the same pair; `evidence.series` holds the yearly scores |
| `bilateral_events` | 1 | `/analyze` `partners` | bilateral questions only: the named pair's activity today |

**Headline verification.** `/article-relevance` fetches the source article and
reports whether it names the event's two actors. It uses no AI model. Its
`link` sets `evidence.verification.status`:

| `link` | status | confidence |
|---|---|---|
| `together`: both actors named in one descriptive sentence | `verified` | 0.55 |
| `listed` / `one_sided`: named only in a list, or only one actor named | `weak` | 0.35 |
| `none`: neither actor named | `mistagged` | 0.15 |
| `unavailable`, or the call failed | `unverified` | 0.45 |

Many news sites refuse non-browser fetches (HTTP 403), so the article text is
often unavailable. In that case the adapter falls back to the URL: if the slug
is descriptive (four or more subject words) and names neither actor, the event
is `mistagged` with `verification.method` `url_only` and confidence at most
0.2. Only country actors are checked this way. A role label ("Police") or a
generic one ("an unidentified party") has no name a slug would carry, so it
leaves the event unverified. A `mistagged` claim reads "Likely mis-tagged by
GDELT: ...". The summary takes each agent's strongest claim, and at 0.15-0.2 a
flagged headline always ranks below the day's activity claim (at least 0.3),
so it stays out of the summary.

A failed relevance call is marked handled and does not make the Events result
`partial`. The same applies to a `/historical-context` 404, which means GGE has
no series for that pair (for example China-Taiwan); the adapter adds a note
naming the pair. A 503 means the GGE file is missing, and still makes the
result `partial`.

## How confidence is set where a module does not publish one

| Agent | Basis |
|---|---|
| Trade | the module's own confidence model, passed through unchanged |
| Soft Power | `0.92 - 0.5 * min(1, interval_width / 30)` from the Kalman 95% interval on the 0-100 scale; fixed values for historical points, SHAP drivers and peers |
| Policy Stance | the bloc's provenance: `vote_model` 0.70, `override_replaced` 0.60 (the module's own model placement recovered from behind a hard-coded label), `fallback_rule` 0.35, `anchor` 0.30, `manual_override` 0.25; conflict totals 0.60 |
| Events | day claims: `min(0.7, 0.3 + 0.1 * log10(1 + events))`, capped because GDELT coding is noisy. Themes: `0.35 + 0.5 * (silhouette - max(0, shuffled silhouette))` under the same cap; at most 0.35 when the module rates the clusters weak, and at most 0.4 when it did not validate them. Domestic split: at most 0.4. Headlines: set by verification, as in the table above. GGE baseline: 0.75 |

## Orchestrator API

| Method | Path | Purpose |
|---|---|---|
| POST | `/ask` | `{question, agents?, countries?, intent?, year?, date?, sector?, severity?, include_envelopes?}` → plan, time alignment, fused findings, briefing, per-agent envelopes and call logs. Unknown fields are rejected (422), as in the Trade agent. |
| POST | `/parse` | the plan `/ask` would execute, without calling any agent |
| GET | `/agents` | live health of the four agents |
| GET | `/capabilities` | the orchestrator's intents plus each agent's self-description |
| GET | `/health` | liveness plus a one-word status per agent |
| GET | `/` | briefing UI |
