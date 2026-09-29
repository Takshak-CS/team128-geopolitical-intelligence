"""Policy Stance adapter (Santhosh's module, FastAPI over UCDP + UN GA voting).

Native API (name-keyed, Gleditsch-Ward codes underneath):
    GET /status                    pipeline readiness (the module loads data in a background thread)
    GET /countries                 [{name, gw_code}] for sovereign states with a profile
    GET /country/{name}            conflict record, centrality, UN vote counts, top partners
    GET /alliance-blocs            {country_to_bloc, blocs} over the full voting history
    GET /blocs-by-year/{year}      {name: bloc} from a 7-year voting window ending at year
    GET /compare-insight           pairwise similarity, bloc, vote match rate, drift
    GET /forecast                  linear conflict-activity trend

Identity: this adapter never trusts a country *name* across the boundary. It maps
ISO3 -> GW code with the orchestrator's crosswalk, then finds the module's name
for that GW code through ``/countries``.

Bloc provenance. The module assigns blocs by cosine similarity of a country's
voting (or voting-graph embedding) to the centroid of hand-picked *anchor*
countries per bloc, and applies manual overrides afterwards. So for some
countries the bloc is an input, not a finding. Every alignment insight says
which case it is, and confidence follows:

    vote_model       similarity of the country's own votes to the bloc anchors
    anchor           the country is one of the bloc's defining anchors
    manual_override  hard-coded in MANUAL_OVERRIDES (currently India, Sri Lanka)
    fallback_rule    no UN votes loaded; placed by a hand-written rule or the default
"""

from __future__ import annotations

import math
from typing import Optional
from urllib.parse import quote

from .. import countries
from ..contract import insight
from ..intent import QueryPlan
from .base import AgentAdapter, AgentNotReady, AgentResult, try_call

# Mirrors backend/main.py and backend/ml_analysis.py in the Policy Stance module.
MANUAL_OVERRIDES = {"India": "Non-Aligned", "Sri Lanka": "China-Centered Bloc"}
ANCHORS_FULL_HISTORY = {
    "Western Bloc": {"USA", "UK", "France", "Germany", "Japan", "Australia", "Canada", "Netherlands"},
    "Russia+Allies": {"Russia", "Belarus", "North Korea", "Syria"},
    "China-Centered Bloc": {"China", "Cambodia", "Laos"},
    "Non-Aligned": {"India", "Brazil", "South Africa", "Indonesia", "Nigeria", "Egypt"},
}
ANCHORS_BY_YEAR = {
    "Western Bloc": {"USA", "UK", "France", "Germany", "Japan", "Australia", "Canada"},
    "Russia+Allies": {"Russia", "Belarus", "North Korea", "Syria"},
    "China-Centered Bloc": {"China", "Pakistan", "Cambodia"},
    "Non-Aligned": {"Brazil", "South Africa", "Indonesia", "Egypt"},
}

PROVENANCE_CONFIDENCE = {"vote_model": 0.7, "override_replaced": 0.6, "fallback_rule": 0.35, "anchor": 0.3, "manual_override": 0.25}
PROVENANCE_NOTE = {
    "override_replaced": "the module hard-codes a different label for it; this is its own UN-vote model's placement, taken from the full 1989-2025 voting history rather than the aligned year",
    "vote_model": "placed by the similarity of its own UN votes to each bloc's anchor countries",
    "anchor": "one of the anchor countries that define this bloc, so the placement is an input to the model rather than a finding",
    "manual_override": "hard-coded to this bloc by a manual override in the module; the voting model's own placement is not exposed",
    "fallback_rule": "no UN voting records loaded for it, so it was placed by a hand-written fallback rule or the default bloc",
}

# Extra GW codes the module's data may use for a country, tried after the standard one.
_GW_ALTERNATES = {"DEU": [255], "YEM": [679], "SRB": [345], "RUS": [], "MMR": [772]}


class PolicyStanceAdapter(AgentAdapter):
    name = "policy_stance"
    label = "Policy Stance"
    description = "UN General Assembly voting similarity, alliance blocs and UCDP conflict graphs (1989-2025)."
    time_grain = "annual (1989-2025)"

    async def capabilities(self) -> dict:
        # Try to pull the live self-description from the module first.
        try:
            return await self.get("/capabilities", timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
        return {
            "agent": self.name,
            "description": self.description,
            "time_grain": self.time_grain,
            "join_key": "Gleditsch-Ward code -> ISO3 (orchestrator crosswalk)",
            "native_endpoints": [
                "/status", "/health", "/capabilities",
                "/countries", "/country/{name}",
                "/alliance-blocs", "/blocs-by-year/{year}", "/bloc-discovery/{year}",
                "/compare-insight", "/forecast",
            ],
        }

    async def health(self) -> dict:
        base = await super().health()
        if base["status"] == "ok":
            return base
        # Try the native /health endpoint added in the Team 128 integration.
        # Fall back to /status for older deployments that pre-date it.
        for path in ("/health", "/status"):
            try:
                data = await self.get(path, timeout=5.0)
                ready = bool(data.get("ready") if path == "/status" else data.get("status") == "ok")
                return {"status": "ok" if ready else "not_ready", "detail": data}
            except Exception:  # noqa: BLE001
                continue
        return {"status": "unreachable", "detail": "both /health and /status failed"}

    # -------------------------------------------------------------- identity
    async def _gw_names(self) -> dict[int, str]:
        rows = await self.cached_get("/countries", ttl_s=600)
        out: dict[int, str] = {}
        for row in rows or []:
            try:
                out[int(row["gw_code"])] = str(row["name"])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _module_name(iso3: str, gw_names: dict[int, str]) -> Optional[str]:
        country = countries.get(iso3)
        if not country or country.gw is None:
            return None
        for code in [country.gw, *_GW_ALTERNATES.get(iso3, [])]:
            if code in gw_names:
                return gw_names[code]
        return None

    @staticmethod
    def _name_to_iso3(gw_names: dict[int, str]) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for code, name in gw_names.items():
            iso3 = countries.GW_TO_ISO3.get(code)
            if iso3:
                mapping.setdefault(name, iso3)
        return mapping

    # ------------------------------------------------------------------ run
    async def collect(self, plan: QueryPlan, result: AgentResult) -> tuple[list[dict], dict]:
        status = await self.get("/status")
        if not status.get("ready"):
            raise AgentNotReady(f"Policy Stance pipeline not ready: {status.get('progress')}")
        if not status.get("node_count"):
            result.notes.append("Policy Stance is running but loaded no datasets; see docs/DATA.md.")

        gw_names = await self._gw_names()
        name_to_iso3 = self._name_to_iso3(gw_names)
        bloc_map, bloc_source, anchors = await self._blocs(plan, result)
        overrides = await self._model_behind_overrides(bloc_map)
        bloc_by_iso3 = {name_to_iso3[name]: bloc for name, bloc in bloc_map.items() if name in name_to_iso3}
        replaced = {name_to_iso3[name]: pair for name, pair in overrides.items() if name in name_to_iso3}
        for iso3, pair in replaced.items():
            bloc_by_iso3[iso3] = pair["model"]
        result.context.update({"bloc_by_iso3": bloc_by_iso3, "bloc_source": bloc_source, "overridden_blocs": replaced})

        metadata = {
            "query_type": plan.intent,
            "year": plan.time.year if plan.time.mode == "year" else result.context.get("bloc_year"),
            "time_grain": "annual",
            "method": "UN GA vote similarity to anchor-country centroids; UCDP conflict graph",
            "bloc_source": bloc_source,
            "data_quality": {"countries_profiled": len(gw_names), "graph_nodes": status.get("node_count"), "datasets": status.get("dataset_count")},
        }

        if not plan.entities:
            return self._bloc_overview(bloc_by_iso3, bloc_source), metadata

        targets = plan.iso3s[:2] if plan.intent == "bilateral" else plan.iso3s[:1]
        insights: list[dict] = []
        provenance: dict[str, str] = {}
        for iso3 in targets:
            module_name = self._module_name(iso3, gw_names)
            if not module_name:
                insights.append(
                    insight(iso3, f"{countries.name_of(iso3)} has no profile in the Policy Stance data.", 0.0, 0.8, "country not present in the loaded UCDP/UN voting data", {"covered": False}, facet="diplomatic_alignment")
                )
                continue
            profile = await try_call(self.get(f"/country/{quote(module_name, safe='')}"), None)
            prov = "override_replaced" if iso3 in replaced else self._provenance(module_name, profile, anchors)
            provenance[iso3] = prov
            insights.extend(self._profile_insights(iso3, module_name, profile, bloc_by_iso3.get(iso3), prov, bloc_source, bloc_by_iso3, replaced.get(iso3)))
            if plan.intent == "forecast":
                insights.extend(await self._forecast(iso3, module_name))
        result.context["bloc_provenance"] = provenance

        if plan.intent == "bilateral" and len(targets) == 2:
            names = [self._module_name(code, gw_names) for code in targets]
            if all(names):
                insights.extend(await self._compare(targets, names))

        # Louvain-discovered blocs — supplement the anchor-based bloc assignments
        # with unsupervised community detection so the briefing can note when the
        # two methods agree or disagree.
        if targets:
            year = plan.time.year if plan.time.mode == "year" else result.context.get("bloc_year") or 2024
            insights.extend(await self._bloc_discovery_insights(targets, bloc_by_iso3, gw_names, int(year)))

        # Issue-level UN voting and conflict stance — unique to this module.
        for iso3 in targets:
            module_name = self._module_name(iso3, gw_names)
            if module_name:
                stance = await self._issue_stance(iso3, module_name)
                if stance:
                    insights.append(stance)

        # Conflict network changes for the queried year — uses /graph-delta.
        if targets and plan.time.mode == "year":
            delta_year = plan.time.year
            delta = await self._conflict_network_delta(targets, gw_names, int(delta_year))
            if delta:
                insights.append(delta)

        # Bilateral: temporal voting drift — uses /temporal-agreement.
        if plan.intent == "bilateral" and len(targets) == 2:
            ta_insight = await self._temporal_agreement_insight(targets, gw_names)
            if ta_insight:
                insights.append(ta_insight)

        return insights, metadata

    async def _blocs(self, plan: QueryPlan, result: AgentResult) -> tuple[dict, str, dict]:
        year = plan.time.year if plan.time.mode == "year" else self.shared.get("aligned_year")
        if year:
            by_year = await try_call(self.cached_get(f"/blocs-by-year/{int(year)}", ttl_s=600), None)
            if isinstance(by_year, dict) and by_year:
                result.context["bloc_year"] = int(year)
                return by_year, f"/blocs-by-year/{int(year)}", ANCHORS_BY_YEAR
        full = await try_call(self.cached_get("/alliance-blocs", ttl_s=600), {})
        return (full or {}).get("country_to_bloc", {}), "/alliance-blocs", ANCHORS_FULL_HISTORY

    async def _model_behind_overrides(self, bloc_map: dict) -> dict[str, dict]:
        """The module's own vote-model bloc for countries it hard-codes.

        ``/alliance-blocs`` and ``/blocs-by-year`` apply MANUAL_OVERRIDES after the
        model runs, but ``/compare-insight`` reads the model's assignment directly,
        so it exposes what the override hides (India: published Non-Aligned, model
        China-Centered Bloc).
        """
        found: dict[str, dict] = {}
        for name, published in MANUAL_OVERRIDES.items():
            if name not in bloc_map:
                continue
            reference = "USA" if name != "USA" else "UK"
            payload = await try_call(self.cached_get("/compare-insight", params={"country_a": name, "country_b": reference}, ttl_s=600), None)
            model = ((payload or {}).get("metrics") or {}).get("bloc_a")
            if model and model != "Unknown":
                found[name] = {"published": bloc_map.get(name, published), "model": model}
        return found

    @staticmethod
    def _provenance(module_name: str, profile: Optional[dict], anchors: dict) -> str:
        if module_name in MANUAL_OVERRIDES:
            return "manual_override"
        if any(module_name in members for members in anchors.values()):
            return "anchor"
        votes = ((profile or {}).get("un_votes") or {}).get("counts") or {}
        if not any(count for count in votes.values()):
            return "fallback_rule"
        return "vote_model"

    # ---------------------------------------------------------------- views
    def _profile_insights(self, iso3, module_name, profile, bloc, prov, bloc_source, bloc_by_iso3, override=None) -> list[dict]:
        name = countries.name_of(iso3)
        out: list[dict] = []
        if bloc:
            members = sorted(code for code, other in bloc_by_iso3.items() if other == bloc)
            if override:
                claim = (
                    f"Policy Stance publishes {name} as {override['published']}, but that label is a hard-coded override: "
                    f"the module's own UN-vote model places {name} in the {override['model']}."
                )
            else:
                claim = f"Policy Stance places {name} in the {bloc} ({len(members)} members) - {PROVENANCE_NOTE[prov]}."
            evidence = {"bloc": bloc, "provenance": prov, "bloc_size": len(members), "bloc_source": bloc_source, "module_name": module_name, "members_sample": [countries.name_of(m) for m in members[:8]]}
            if override:
                evidence.update({"published_bloc": override["published"], "model_bloc": override["model"], "model_source": "/compare-insight (full 1989-2025 voting history)"})
            out.append(
                insight(
                    iso3,
                    claim,
                    len(members) / max(1, len(bloc_by_iso3)),
                    PROVENANCE_CONFIDENCE[prov],
                    f"bloc provenance: {prov}",
                    evidence,
                    facet="diplomatic_alignment",
                )
            )
        if not profile:
            return out

        # Totals come from the per-year timeline, which aggregates every conflict
        # row involving the country. The profile's node-level total_conflicts /
        # total_deaths disagree with it (India: 1 and 0 vs 664 rows, 59,215 deaths).
        timeline = [t for t in (profile.get("timeline") or []) if isinstance(t, dict)]
        conflicts = sum(int(t.get("conflicts") or 0) for t in timeline)
        deaths = sum(float(t.get("deaths") or 0) for t in timeline)
        active = sorted(int(t["year"]) for t in timeline if (t.get("conflicts") or 0) > 0)
        recent_deaths = sum(float(t.get("deaths") or 0) for t in timeline if active and int(t["year"]) >= active[-1] - 4)
        issues = [item.get("issue") for item in (profile.get("top_issues") or [])[:3] if item.get("issue")]
        if conflicts or deaths:
            span = f"{active[0]}-{active[-1]}" if active else "the loaded years"
            out.append(
                insight(
                    iso3,
                    f"UCDP data links {name} to {conflicts} conflict records and {deaths:,.0f} deaths over {span}, "
                    f"{recent_deaths:,.0f} of them in the last five active years"
                    + (f"; recurring issues: {', '.join(issues)}." if issues else "."),
                    min(1.0, math.log10(1 + deaths) / 6.0),
                    0.6,
                    "UCDP-curated data, summed across the loaded UCDP datasets, which can count the same conflict in more than one of them",
                    {"conflict_records": conflicts, "deaths": deaths, "recent_deaths_5y": recent_deaths, "active_years": active[-10:], "top_issues": issues, "centrality": profile.get("centrality")},
                    facet="conflict_exposure",
                )
            )
        else:
            out.append(
                insight(iso3, f"UCDP records no armed-conflict involvement for {name} in the loaded data.", 0.0, 0.7, "absence of records in UCDP; not proof of no tension", {"total_conflicts": 0}, facet="conflict_exposure")
            )

        partners = [p for p in (profile.get("top_partners") or []) if (p.get("un_agree_rate") or 0) > 0]
        partners.sort(key=lambda p: p.get("un_agree_rate") or 0, reverse=True)
        resolved: list[dict] = []
        for p in partners:
            # Defunct states (East Germany, Yemen PDR, ...) voted only in 1989-1991,
            # so their high agreement rates rest on a handful of resolutions.
            partner_iso3 = countries.GW_TO_ISO3.get(int(p.get("gw_code") or 0))
            if partner_iso3:
                resolved.append({"iso3": partner_iso3, "name": countries.name_of(partner_iso3), "un_agree_rate": p.get("un_agree_rate"), "conflict_count": p.get("conflict_count")})
            if len(resolved) == 5:
                break
        if resolved:
            text = ", ".join(f"{r['name']} ({(r['un_agree_rate'] or 0) * 100:.0f}%)" for r in resolved[:3])
            out.append(
                insight(
                    iso3,
                    f"Among its network partners, {name} votes most often with {text} at the UN.",
                    resolved[0]["un_agree_rate"] or 0,
                    0.65,
                    "agreement over resolutions both voted on; limited to partners linked in the conflict/agreement graph",
                    {"partners": resolved},
                    facet="diplomatic_partners",
                )
            )
        return out

    async def _conflict_network_delta(self, iso3s: list[str], gw_names: dict[int, str], year: int) -> Optional[dict]:
        """Use /graph-delta/{year} to report which conflicts started or ended in this year."""
        delta = await try_call(self.cached_get(f"/graph-delta/{year}", ttl_s=600), None)
        if not isinstance(delta, dict):
            return None
        new_edges: list[dict] = delta.get("new_edge_names", [])
        ended_edges: list[dict] = delta.get("ended_edge_names", [])
        new_total: int = delta.get("new_edges", 0)
        ended_total: int = delta.get("ended_edges", 0)
        if not new_total and not ended_total:
            return None

        # Filter to edges involving any queried country
        name_to_iso3 = self._name_to_iso3(gw_names)
        queried_names = {gw_names.get(countries.get(iso3).gw) for iso3 in iso3s if countries.get(iso3) and countries.get(iso3).gw}
        queried_names.discard(None)

        def _involves(edge: dict) -> bool:
            return edge.get("source") in queried_names or edge.get("target") in queried_names

        relevant_new = [e for e in new_edges if _involves(e)][:5]
        relevant_ended = [e for e in ended_edges if _involves(e)][:5]

        if not relevant_new and not relevant_ended:
            # Return a global delta claim if no direct involvement
            if new_total + ended_total < 2:
                return None
            claim = f"In {year}, the global conflict network saw {new_total} new conflict links and {ended_total} ended, for a net {'increase' if new_total > ended_total else 'decrease'}."
            evidence = {"year": year, "new_edges": new_total, "ended_edges": ended_total, "node_count": delta.get("nodes"), "edge_count": delta.get("edges")}
        else:
            new_str = "; ".join(f"{e['source']} ↔ {e['target']}" for e in relevant_new[:3]) if relevant_new else "none"
            ended_str = "; ".join(f"{e['source']} ↔ {e['target']}" for e in relevant_ended[:3]) if relevant_ended else "none"
            country_name = countries.name_of(iso3s[0])
            claim = (
                f"Conflict network change in {year} involving {country_name}: "
                f"{len(relevant_new)} new link(s) ({new_str}); "
                f"{len(relevant_ended)} ended link(s) ({ended_str}). "
                f"Globally: {new_total} new, {ended_total} ended conflict edges."
            )
            evidence = {
                "year": year, "global_new": new_total, "global_ended": ended_total,
                "relevant_new": relevant_new, "relevant_ended": relevant_ended,
                "node_count": delta.get("nodes"), "edge_count": delta.get("edges"),
            }

        return insight(
            iso3s[0],
            claim,
            min(1.0, (new_total + ended_total) / 20),
            0.55,
            "UCDP conflict network graph delta between consecutive years",
            evidence,
            facet="conflict_outlook",
        )

    async def _temporal_agreement_insight(self, iso3s: list[str], gw_names: dict[int, str]) -> Optional[dict]:
        """Use /temporal-agreement to show UN vote drift between two countries over decades."""
        names = [self._module_name(iso3, gw_names) for iso3 in iso3s]
        if not all(names):
            return None
        ta_all: dict = await try_call(self.cached_get("/temporal-agreement", ttl_s=600), None) or {}
        if not ta_all:
            return None

        # The key format is "CountryA||CountryB" or "CountryA-CountryB"
        key = None
        for sep in ["||", "-"]:
            k1 = f"{names[0]}{sep}{names[1]}"
            k2 = f"{names[1]}{sep}{names[0]}"
            if k1 in ta_all:
                key = k1; break
            if k2 in ta_all:
                key = k2; break
        if not key:
            return None

        year_map: dict = ta_all[key]
        if not isinstance(year_map, dict) or not year_map:
            return None

        sorted_years = sorted(year_map.keys())
        early = [float(year_map[y]) for y in sorted_years[:5] if isinstance(year_map[y], (int, float))]
        recent = [float(year_map[y]) for y in sorted_years[-5:] if isinstance(year_map[y], (int, float))]
        if not early or not recent:
            return None

        early_avg = round(sum(early) / len(early) * 100, 1)
        recent_avg = round(sum(recent) / len(recent) * 100, 1)
        drift = round(recent_avg - early_avg, 1)
        direction = "converging" if drift > 3 else "diverging" if drift < -3 else "stable"
        a_name, b_name = countries.name_of(iso3s[0]), countries.name_of(iso3s[1])

        return insight(
            iso3s[0],
            f"UN vote agreement between {a_name} and {b_name}: {early_avg}% in the {sorted_years[0]}s → {recent_avg}% recently ({direction}, Δ{drift:+.1f}pp across {len(sorted_years)} years).",
            abs(drift) / 50,
            0.65,
            f"year-by-year UN GA vote agreement rate over {len(sorted_years)} years of shared voting",
            {
                "early_avg_pct": early_avg,
                "recent_avg_pct": recent_avg,
                "drift_pp": drift,
                "direction": direction,
                "years_covered": len(sorted_years),
                "series": {y: round(float(year_map[y]) * 100, 1) for y in sorted_years[-10:] if isinstance(year_map[y], (int, float))},
            },
            facet="bilateral_diplomacy",
        )

    async def _issue_stance(self, iso3: str, module_name: str) -> Optional[dict]:
        """Call /policy-stance and /topics to produce an issue_stance insight.

        This endpoint is unique to the Policy Stance module — no other agent
        reports which specific UN-voting topics and UCDP conflict issues a
        country is most active on, with Yes/No/Abstain percentages.
        """
        # Get the country's UN voting topic distribution (top 5 topics)
        votes_profile = await try_call(
            self.cached_get(f"/country/{module_name}", ttl_s=600), None
        )
        if not votes_profile:
            return None

        top_topics: dict = (votes_profile.get("un_votes") or {}).get("top_topics") or {}
        vote_counts: dict = (votes_profile.get("un_votes") or {}).get("counts") or {}
        top_issues: list = (votes_profile.get("top_issues") or [])[:5]

        if not top_topics and not top_issues:
            return None

        name = countries.name_of(iso3)
        total_yes = vote_counts.get("yes", 0) + vote_counts.get("Y", 0)
        total_no = vote_counts.get("no", 0) + vote_counts.get("N", 0)
        total_abstain = vote_counts.get("abstain", 0) + vote_counts.get("A", 0)
        total_votes = total_yes + total_no + total_abstain

        parts: list[str] = []
        if total_votes:
            pct_yes = round(total_yes / total_votes * 100)
            pct_no = round(total_no / total_votes * 100)
            pct_abs = round(total_abstain / total_votes * 100)
            parts.append(
                f"Across {total_votes:,} UN GA votes, {name} voted Yes {pct_yes}%, No {pct_no}%, Abstain {pct_abs}%."
            )

        if top_topics:
            top3 = sorted(top_topics.items(), key=lambda kv: kv[1], reverse=True)[:3]
            topic_str = "; ".join(f"{t} ({n} resolutions)" for t, n in top3)
            parts.append(f"Most active UN voting topics: {topic_str}.")

        if top_issues:
            issue_str = ", ".join(
                str(item.get("issue", "")) for item in top_issues if item.get("issue")
            )
            if issue_str:
                parts.append(f"Dominant UCDP conflict issues: {issue_str}.")

        if not parts:
            return None

        return insight(
            iso3,
            " ".join(parts),
            min(1.0, total_votes / 5000) if total_votes else 0.3,
            0.70 if total_votes > 100 else 0.40,
            "UN GA vote distribution from the full 1989-2025 voting record; UCDP issue codes from conflict datasets",
            {
                "total_votes": total_votes,
                "vote_breakdown": {"yes": total_yes, "no": total_no, "abstain": total_abstain},
                "top_topics": dict(list(top_topics.items())[:5]),
                "top_issues": top_issues[:5],
            },
            facet="issue_stance",
        )

    async def _bloc_discovery_insights(self, iso3s: list[str], anchor_blocs: dict[str, str], gw_names: dict[int, str], year: int) -> list[dict]:
        """Call /bloc-discovery and produce one diplomatic_blocs insight per country.

        Compares Louvain-discovered clusters (no pre-labelled anchors) against
        the anchor-similarity blocs already in anchor_blocs. When they agree the
        confidence in the diplomatic alignment claim is higher; when they diverge
        it is surfaced as a caveat for fusion to flag.
        """
        disc = await try_call(self.cached_get(f"/bloc-discovery/{year}", ttl_s=600), None)
        if not isinstance(disc, dict) or "country_to_cluster" not in disc:
            return []
        c2c: dict[str, int] = disc.get("country_to_cluster", {})
        clusters: list[dict] = disc.get("clusters", [])
        if not c2c or not clusters:
            return []

        # Build cluster-id → set of ISO3 so we can name cluster members
        cluster_iso3s: dict[int, list[str]] = {}
        name_to_iso3 = self._name_to_iso3(gw_names)
        for module_name, cid in c2c.items():
            m_iso3 = name_to_iso3.get(module_name)
            if m_iso3:
                cluster_iso3s.setdefault(cid, []).append(m_iso3)

        out: list[dict] = []
        for iso3 in iso3s:
            module_name = self._module_name(iso3, gw_names)
            if not module_name or module_name not in c2c:
                continue
            cid = c2c[module_name]
            cluster_members_iso3 = cluster_iso3s.get(cid, [])
            anchor_bloc = anchor_blocs.get(iso3, "Unknown")

            # What anchor-labelled blocs appear most in this cluster?
            bloc_votes: dict[str, int] = {}
            for m in cluster_members_iso3:
                b = anchor_blocs.get(m)
                if b:
                    bloc_votes[b] = bloc_votes.get(b, 0) + 1
            dominant_bloc = max(bloc_votes, key=bloc_votes.get) if bloc_votes else "Unknown"
            agrees = dominant_bloc == anchor_bloc

            sample = [countries.name_of(m) for m in sorted(cluster_members_iso3) if m != iso3][:5]
            name = countries.name_of(iso3)
            claim = (
                f"Louvain community detection (no pre-set labels) places {name} in cluster {cid} "
                f"({len(cluster_members_iso3)} members), which aligns with the {dominant_bloc} "
                f"({'consistent with' if agrees else 'diverging from'} the anchor-similarity assignment)."
            )
            caveat = None if agrees else (
                f"Louvain cluster {cid} is dominated by the {dominant_bloc} label, but the "
                f"anchor-similarity method places {name} in the {anchor_bloc}. "
                f"Fusion should treat this as a methodological disagreement, not a factual one."
            )
            out.append(
                insight(
                    iso3,
                    claim,
                    len(cluster_members_iso3) / max(1, disc.get("countries", 1)),
                    0.60 if agrees else 0.45,
                    f"Louvain on {year - 7}-{year} vote-similarity network; no manual overrides applied",
                    {
                        "cluster_id": cid,
                        "cluster_size": len(cluster_members_iso3),
                        "cluster_members_sample": sample,
                        "dominant_bloc_in_cluster": dominant_bloc,
                        "anchor_bloc": anchor_bloc,
                        "method_agrees": agrees,
                        "total_clusters": len(clusters),
                        "discovery_year": year,
                    },
                    facet="diplomatic_blocs",
                    caveat=caveat,
                )
            )
        return out

    def _bloc_overview(self, bloc_by_iso3: dict, bloc_source: str) -> list[dict]:
        groups: dict[str, list[str]] = {}
        for iso3, bloc in bloc_by_iso3.items():
            groups.setdefault(bloc, []).append(iso3)
        out = []
        total = max(1, len(bloc_by_iso3))
        for bloc, members in sorted(groups.items(), key=lambda item: -len(item[1])):
            sample = ", ".join(countries.name_of(m) for m in sorted(members)[:6])
            out.append(
                insight(
                    None,
                    f"{bloc}: {len(members)} countries by UN voting (e.g. {sample}).",
                    len(members) / total,
                    0.6,
                    "bloc membership is similarity to hand-picked anchor countries, not unsupervised clustering",
                    {"bloc": bloc, "size": len(members), "members": sorted(members), "bloc_source": bloc_source},
                    facet="diplomatic_blocs",
                    entity_name=bloc,
                )
            )
        return out

    async def _compare(self, pair: list[str], names: list[str]) -> list[dict]:
        payload = await try_call(self.get("/compare-insight", params={"country_a": names[0], "country_b": names[1]}), None)
        if not payload:
            return []
        metrics = payload.get("metrics") or {}
        similarity = float(metrics.get("similarity") or 0.0)
        bullets = payload.get("bullets") or []
        a, b = (countries.name_of(code) for code in pair)
        match_rate = metrics.get("vote_match_rate")
        claim = f"{a} and {b}: vote-and-conflict profile similarity {similarity:.2f}"
        claim += f"; same bloc ({metrics.get('bloc_a')})" if metrics.get("same_bloc") else f"; different blocs ({metrics.get('bloc_a')} vs {metrics.get('bloc_b')})"
        if match_rate is not None:
            claim += f"; voted the same way on {match_rate:.0f}% of sampled resolutions"
        claim += "."
        return [
            insight(
                pair[0],
                claim,
                similarity,
                0.7 if match_rate is not None else 0.5,
                "vote match rate over up to 100 recent shared resolutions" if match_rate is not None else "no overlapping UN voting record; similarity rests on conflict features",
                {"pair": pair, "metrics": metrics, "module_summary": bullets[:4]},
                facet="bilateral_diplomacy",
            )
        ]

    async def _forecast(self, iso3: str, module_name: str) -> list[dict]:
        payload = await try_call(self.get("/forecast", params={"countries": module_name, "metric": "conflicts", "horizon": 5}), None)
        series = (payload or {}).get("forecasts") or []
        if not series:
            return []
        item = series[0]
        last = (item.get("forecast") or [{}])[-1]
        return [
            insight(
                iso3,
                f"Conflict-activity trend for {countries.name_of(iso3)} is {item.get('trend')} (linear fit over the last 15 years; {last.get('forecast')} projected for {last.get('year')}).",
                0.0,
                0.45,
                "straight-line fit on yearly conflict counts; no uncertainty band is produced",
                {"trend": item.get("trend"), "forecast": item.get("forecast")},
                facet="conflict_outlook",
            )
        ]

