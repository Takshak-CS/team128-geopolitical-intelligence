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
      "facet": "trade_exposure"
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
- `app.contract.validate_envelope` checks the required fields and the
  confidence range. Fusion reports violations under `fused.contract_issues`
  instead of failing.

## Facets by agent

| Agent | Facets | Native call(s) |
|---|---|---|
| Soft Power | `influence`, `influence_trend`, `influence_outlook`, `influence_drivers`, `influence_peers`, `bilateral_influence` | `/api/latest`, `/api/timeseries`, `/api/forecast/{iso3}`, `/api/drivers/{iso3}`, `/api/peers/{iso3}` |
| Policy Stance | `diplomatic_alignment`, `diplomatic_partners`, `conflict_exposure`, `conflict_outlook`, `bilateral_diplomacy`, `diplomatic_blocs` | `/status`, `/countries`, `/blocs-by-year/{y}` (or `/alliance-blocs`), `/country/{name}`, `/compare-insight`, `/forecast` |
| Trade | `trade_exposure` (risk), `trade_alignment` (blocs), `trade_dependence` (leverage), `supply_fragility`, `shock_impact`, `trade_outlook` (forecast), `bilateral_trade_bloc`, `bilateral_trade_dependence` | `POST /query`, `/capabilities` |
| Events | `event_activity`, `event_partners`, `event_headline`, `bilateral_events`, `relationship_baseline` | `POST /analyze`, `/historical-context` |

## How confidence is set where a module does not publish one

| Agent | Basis |
|---|---|
| Trade | the module's own confidence model, passed through unchanged |
| Soft Power | `0.92 - 0.5 * min(1, interval_width / 30)` from the Kalman 95% interval on the 0-100 scale; fixed values for historical points, SHAP drivers and peers |
| Policy Stance | the bloc's provenance: `vote_model` 0.70, `override_replaced` 0.60 (the module's own model placement recovered from behind a hard-coded label), `fallback_rule` 0.35, `anchor` 0.30, `manual_override` 0.25; conflict totals 0.60 |
| Events | `min(0.7, 0.3 + 0.1 * log10(1 + events))`, capped because GDELT coding is noisy; GGE baseline 0.75 |

## Orchestrator API

| Method | Path | Purpose |
|---|---|---|
| POST | `/ask` | `{question, agents?, countries?, intent?, year?, date?, sector?, severity?, include_envelopes?}` → plan, time alignment, fused findings, briefing, per-agent envelopes and call logs. Unknown fields are rejected (422), as in the Trade agent. |
| POST | `/parse` | the plan `/ask` would execute, without calling any agent |
| GET | `/agents` | live health of the four agents |
| GET | `/capabilities` | the orchestrator's intents plus each agent's self-description |
| GET | `/health` | liveness plus a one-word status per agent |
| GET | `/` | briefing UI |
