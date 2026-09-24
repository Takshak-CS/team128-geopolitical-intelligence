import glob
import json
import os
from pathlib import Path
import pickle
import re
import threading

# Human-readable labels for UCDP issue numeric codes still in cached data
_ISSUE_CODE_MAP: dict[str, str] = {
    # Ideology / government system
    "7101": "Ideology", "7201": "Communist ideology", "7202": "Marxist ideology",
    "7203": "Left-wing ideology", "7301": "Nationalist ideology", "7302": "Right-wing nationalism",
    "7303": "Ethnic nationalism", "7304": "Religious nationalism", "7401": "Secessionist ideology",
    "7501": "Islamist ideology", "7502": "Jihadist ideology", "7601": "Anarchist ideology",
    # Political system / governance
    "2101": "Political exclusion", "2102": "Political repression", "2103": "Political system",
    "2201": "Elections", "2202": "Electoral fraud", "2203": "Electoral violence",
    "2301": "Corruption/governance", "2302": "Rule of law", "2401": "Power sharing",
    "2501": "Democracy", "2502": "Authoritarianism",
    # Territory
    "9101": "Secession/independence", "9102": "Territorial control", "9103": "Border territory",
    "9201": "Border dispute", "9202": "Maritime border", "9301": "Reunification",
    "9401": "Colonial independence", "9999": "Other territorial issue",
    # Foreign involvement
    "6101": "Security pact", "6102": "Foreign political support", "6103": "Foreign military support",
    "6104": "Foreign financial support", "6105": "Foreign training support",
    "6106": "Foreign political interference", "6107": "Peacekeeping mission",
    "6108": "Foreign volunteers", "6109": "Sanctions", "6110": "Regional organization",
    "6111": "International organization", "6112": "Military alliance",
    "6201": "Foreign intervention", "6202": "Great power involvement",
    "6203": "Neighboring state involvement", "6204": "Diaspora support",
    "6209": "Foreign military presence",
    # Resources / economy
    "4101": "Natural resources", "4102": "Oil/gas", "4103": "Diamonds/minerals",
    "4104": "Drug trade", "4105": "Timber/logging", "4106": "Water rights",
    "4201": "Economic inequality", "4202": "Land ownership", "4203": "Agrarian reform",
    "4204": "Debt", "4205": "Trade", "4206": "Drug economy", "4301": "Land reform",
    "4302": "Property rights", "4305": "Economic policy",
    # Identity / ethnic / religious
    "5101": "Ethnic identity", "5102": "Ethnic autonomy", "5103": "Ethnic discrimination",
    "5104": "Ethnic cleansing", "5201": "Minority rights", "5202": "Cultural rights",
    "5203": "Religious discrimination", "5204": "Religious extremism",
    "5301": "Language rights", "5401": "Caste discrimination",
    # Socioeconomic
    "8101": "Economic development", "8102": "Poverty", "8201": "Economic inequality",
    "8301": "Social services",
    # Autonomy / governance structure
    "3101": "Political autonomy", "3102": "Autonomy", "3103": "Cultural autonomy",
    "3104": "Regional autonomy", "3201": "Federalism demand", "3202": "Federalism",
    # Peace / ceasefire
    "1101": "Territory/government", "1201": "Ceasefire", "1301": "Peace agreement",
    "1401": "Disarmament",
    # Extended / sub-categories (10xxx range)
    "10201": "Governance reform", "10202": "Constitutional reform", "10203": "Institutional reform",
    "10101": "Anti-government protest", "10301": "Social movement",
    "10401": "State failure", "10501": "Coup attempt",
    # Top-level category codes (float-coded in some datasets)
    "1": "Territory/Government", "2": "Territory",
    "1000": "Territory/Government", "1100": "Territory",
    "1200": "Ceasefire", "1300": "Peace agreement", "1400": "Disarmament",
    "2000": "Governance/Political system", "2100": "Political exclusion",
    "2200": "Elections", "2300": "Corruption/governance", "2400": "Power sharing", "2500": "Democracy",
    "3000": "Autonomy/Federalism", "3100": "Political autonomy", "3200": "Federalism",
    "4000": "Resources/Economy", "4100": "Natural resources",
    "4200": "Economic inequality", "4300": "Land reform",
    "5000": "Identity/Ethnic/Religious", "5100": "Ethnic identity",
    "5200": "Minority rights", "5300": "Language rights", "5400": "Caste discrimination",
    "6000": "Foreign involvement", "6100": "Security/alliances",
    "6200": "Foreign intervention",
    "7000": "Ideology", "7100": "Political ideology",
    "7200": "Communist/Marxist ideology", "7300": "Nationalist ideology",
    "7400": "Secessionist ideology", "7500": "Islamist ideology",
    "8000": "Socioeconomic", "8100": "Economic development", "8200": "Economic inequality",
    "8300": "Social services",
    "9000": "Secession/Territory", "9100": "Secession/independence",
    "9200": "Border dispute", "9300": "Reunification", "9400": "Colonial independence",
    "10000": "Other/Unclassified", "11000": "Non-state conflict",
    "11100": "Communal conflict", "11200": "Criminal violence",
}


def _decode_issue_label(label: str) -> str:
    s = label.strip()
    # Strip trailing .0 from float-coded integers (e.g. "3000.0" → "3000")
    if s.endswith('.0') and s[:-2].lstrip('-').isdigit():
        s = s[:-2]
    decoded = _ISSUE_CODE_MAP.get(s)
    return decoded if decoded else label

# Reverse map: "ideology" → ["7101"] so incoming human-readable issues can filter raw numeric data
_REVERSE_ISSUE_MAP: dict[str, list[str]] = {}
for _code, _label in _ISSUE_CODE_MAP.items():
    _REVERSE_ISSUE_MAP.setdefault(_label.lower(), []).append(_code)

from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.codebook_parser import build_codebook
from backend.data_loader import VOTE_DATASETS, discover_datasets, load_all_datasets
from backend.graph_builder import build_graphs
from backend.ml_analysis import run_ml_analysis
from backend.paths import OUTPUTS_DIR, ROOT_DIR, ensure_directories, output_file

RUNTIME_CACHE_PATH = output_file('runtime_cache.pkl')
MASTER_CACHE_PATH = output_file('master_df.pkl')
VOTES_CACHE_PATH = output_file('votes_df.pkl')
CACHE_SENTINEL_PATH = output_file('graph_data.json')


class PipelineState:
    def __init__(self) -> None:
        self.ready = False
        self.progress = 'Queued'
        self.error = ''
        self.data: dict[str, Any] = {}
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()


state = PipelineState()


def _set_progress(message: str) -> None:
    with state.lock:
        state.progress = message


def _pair_key(country_a: str, country_b: str) -> str:
    ordered = sorted([country_a, country_b])
    return f'{ordered[0]}-{ordered[1]}'


def _input_files() -> list[str]:
    dataset_files = list(discover_datasets().values())
    pdf_files = []
    for path in glob.glob(os.path.join(ROOT_DIR, '**', '*.pdf'), recursive=True):
        if any(part in path for part in ['frontend', 'backend', 'outputs', 'node_modules']):
            continue
        pdf_files.append(path)
    return sorted(set(dataset_files + pdf_files))


def _cache_is_fresh() -> bool:
    if not (os.path.exists(CACHE_SENTINEL_PATH) and os.path.exists(RUNTIME_CACHE_PATH)):
        return False
    cache_time = min(os.path.getmtime(CACHE_SENTINEL_PATH), os.path.getmtime(RUNTIME_CACHE_PATH))
    for file_path in _input_files():
        try:
            if os.path.getmtime(file_path) > cache_time:
                return False
        except FileNotFoundError:
            continue
    return True


def _save_runtime_cache(payload: dict[str, Any]) -> None:
    with open(RUNTIME_CACHE_PATH, 'wb') as handle:
        pickle.dump(payload, handle)
    if isinstance(payload.get('master_df'), pd.DataFrame):
        payload['master_df'].to_pickle(MASTER_CACHE_PATH)
    if isinstance(payload.get('votes_df'), pd.DataFrame):
        payload['votes_df'].to_pickle(VOTES_CACHE_PATH)
    with open(output_file('runtime_manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump({'cached': True, 'datasets': len(payload.get('datasets', [])), 'countries': len(payload.get('countries', []))}, handle, indent=2)


def _load_runtime_cache() -> dict[str, Any]:
    with open(RUNTIME_CACHE_PATH, 'rb') as handle:
        return pickle.load(handle)


def _build_country_profiles(graph_json: dict[str, Any], master_df: pd.DataFrame, votes_df: pd.DataFrame, ml_results: dict[str, Any]) -> dict[str, Any]:
    profiles = {}
    # Only build profiles for real sovereign nation-states (GW codes 2-920).
    # Non-state actors (militias, cartels, coalitions) get synthetic codes >= 10000.
    node_by_code = {int(node['gw_code']): node for node in graph_json.get('nodes', []) if node.get('gw_code') is not None and 2 <= int(node['gw_code']) <= 920}
    edges = graph_json.get('edges', [])
    embeddings_2d = ml_results.get('embeddings_2d', {})
    embeddings_3d = ml_results.get('embeddings_3d', {})

    for code, node in node_by_code.items():
        related = master_df[(master_df['country_a_code'] == code) | (master_df['country_b_code'] == code)].copy()
        related = related.sort_values('year', ascending=False) if not related.empty else related
        timeline = []
        if not related.empty:
            grouped = related.groupby('year').agg(intensity=('intensity', 'sum'), deaths=('deaths', 'sum'), conflicts=('dataset', 'count'))
            timeline = [{'year': int(year), 'intensity': float(row['intensity']) if pd.notna(row['intensity']) else 0.0, 'deaths': float(row['deaths']) if pd.notna(row['deaths']) else 0.0, 'conflicts': int(row['conflicts'])} for year, row in grouped.iterrows()]

        partner_rows = []
        for edge in edges:
            if edge['source'] == code or edge['target'] == code:
                partner_code = edge['target'] if edge['source'] == code else edge['source']
                partner = node_by_code.get(int(partner_code))
                if partner:
                    partner_rows.append({'country': partner['name'], 'gw_code': int(partner['gw_code']), 'conflict_count': int(edge.get('conflict_count', 0)), 'agreements': int(edge.get('agreements', 0)), 'un_agree_rate': float(edge.get('un_agree_rate', 0.0))})
        partner_rows.sort(key=lambda item: (item['conflict_count'], item['un_agree_rate']), reverse=True)

        vote_subset = votes_df[votes_df['country_code'] == code].copy()
        vote_summary = Counter(vote_subset['vote'].fillna('UNKNOWN')) if not vote_subset.empty else Counter()
        top_topics = vote_subset['topic'].value_counts().head(10).to_dict() if not vote_subset.empty else {}

        issues_counter = Counter()
        conflicts = []
        for _, row in related.head(50).iterrows():
            if row.get('issue'):
                for issue in [item.strip() for item in str(row.get('issue')).split(',') if item.strip()]:
                    issues_counter[issue] += 1
            partner = row['country_b'] if row.get('country_a_code') == code else row['country_a']
            conflicts.append({'year': int(row['year']), 'dataset': row.get('dataset'), 'issue': row.get('issue'), 'partner': partner, 'intensity': float(row.get('intensity') or 0.0), 'deaths': float(row.get('deaths') or 0.0), 'conflict_name': row.get('conflict_name')})

        profiles[node['name']] = {
            'name': node['name'],
            'gw_code': code,
            'total_conflicts': int(node.get('total_conflicts', 0)),
            'total_deaths': float(node.get('total_deaths', 0.0)),
            'active_years': node.get('active_years', []),
            'centrality': {'degree': float(node.get('degree_centrality', 0.0)), 'betweenness': float(node.get('betweenness_centrality', 0.0)), 'eigenvector': float(node.get('eigenvector_centrality', 0.0)), 'pagerank': float(node.get('pagerank', 0.0))},
            'top_partners': partner_rows[:10],
            'un_votes': {'counts': dict(vote_summary), 'top_topics': top_topics},
            'conflicts': conflicts,
            'timeline': timeline,
            'top_issues': [{'issue': issue, 'count': count} for issue, count in issues_counter.most_common(10)],
            'embedding_2d': embeddings_2d.get(node['name'], [0.0, 0.0]),
            'embedding_3d': embeddings_3d.get(node['name'], [0.0, 0.0, 0.0]),
        }
    return profiles


def _compare_payload(data: dict[str, Any], country_a: str, country_b: str) -> dict[str, Any]:
    profiles = data.get('country_profiles', {})
    temporal_agreement = data.get('temporal_agreement', {})
    similarity = data.get('country_similarity', {})
    votes_df: pd.DataFrame = data.get('votes_df', pd.DataFrame())
    master_df: pd.DataFrame = data.get('master_df', pd.DataFrame())
    profile_a = profiles.get(country_a)
    profile_b = profiles.get(country_b)
    if not profile_a or not profile_b:
        raise HTTPException(status_code=404, detail='Country not found')

    similarity_value = 0.0
    countries = similarity.get('countries', [])
    matrix = similarity.get('matrix', [])
    if country_a in countries and country_b in countries:
        left = countries.index(country_a)
        right = countries.index(country_b)
        similarity_value = matrix[left][right]

    code_a = profile_a['gw_code']
    code_b = profile_b['gw_code']
    shared_conflicts = []
    if not master_df.empty:
        subset = master_df[((master_df['country_a_code'] == code_a) & (master_df['country_b_code'] == code_b)) | ((master_df['country_a_code'] == code_b) & (master_df['country_b_code'] == code_a))].copy()
        subset = subset.sort_values('year', ascending=False)
        for _, row in subset.head(100).iterrows():
            shared_conflicts.append({'year': int(row['year']), 'issue': row.get('issue'), 'intensity': float(row.get('intensity') or 0.0), 'dataset': row.get('dataset'), 'conflict_name': row.get('conflict_name')})

    shared_votes = []
    if not votes_df.empty:
        left_votes = votes_df[votes_df['country_code'] == code_a][['year', 'resolution', 'topic', 'vote', 'title']]
        right_votes = votes_df[votes_df['country_code'] == code_b][['year', 'resolution', 'vote']].rename(columns={'vote': 'vote_b'})
        merged = left_votes.merge(right_votes, on=['year', 'resolution'], how='inner')
        merged['match'] = merged['vote'] == merged['vote_b']
        merged = merged.sort_values(['year', 'resolution'], ascending=[False, True])
        for _, row in merged.head(100).iterrows():
            shared_votes.append({'year': int(row['year']), 'resolution': row['resolution'], 'topic': row.get('topic'), 'vote_a': row['vote'], 'vote_b': row['vote_b'], 'match': bool(row['match'])})

    agreement = temporal_agreement.get(_pair_key(country_a, country_b), {})
    return {'country_a': profile_a, 'country_b': profile_b, 'similarity': similarity_value, 'temporal_agreement': agreement, 'shared_conflicts': shared_conflicts, 'shared_votes': shared_votes}


def _policy_stance_payload(data: dict[str, Any], countries: list[str], issues: list[str], topic: str | None) -> dict[str, Any]:
    master_df: pd.DataFrame = data.get('master_df', pd.DataFrame())
    votes_df: pd.DataFrame = data.get('votes_df', pd.DataFrame())
    profiles = data.get('country_profiles', {})
    selected = [country for country in countries if country in profiles][:10]
    if not selected:
        return {'countries': [], 'issues': [], 'matrix': [], 'agreement_network': {'nodes': [], 'edges': []}, 'rankings': {}, 'temporal': {}, 'resolution_votes': []}

    code_lookup = {country: profiles[country]['gw_code'] for country in selected}
    code_set = set(code_lookup.values())
    normalized_issues = [issue.lower().strip() for issue in issues if issue.strip()]

    # Vectorized filtering — avoid row-by-row iteration over 500K rows
    if master_df.empty:
        relevant = master_df
    else:
        country_mask = master_df['country_a_code'].isin(code_set) | master_df['country_b_code'].isin(code_set)
        issue_str = master_df['issue'].astype(str)
        relevant = master_df[country_mask & master_df['issue'].notna() & (issue_str != '') & (issue_str != 'nan') & (issue_str != 'None')].copy()
        if normalized_issues:
            # Expand human-readable labels to also match their numeric raw codes in cached data
            expanded: list[str] = []
            for ni in normalized_issues:
                expanded.append(ni)
                expanded.extend(_REVERSE_ISSUE_MAP.get(ni, []))
            pattern = '|'.join(re.escape(e) for e in expanded)
            relevant = relevant[relevant['issue'].astype(str).str.contains(pattern, case=False, na=False)]

    counts = defaultdict(Counter)
    temporal = defaultdict(lambda: defaultdict(Counter))
    agreement_edges = Counter()
    issue_pool: list[str] = []

    for _, row in relevant.iterrows():
        candidates = [item.strip() for item in str(row.get('issue') or '').split(',') if item.strip()]
        if not candidates:
            continue
        if normalized_issues:
            # Match candidate against human-readable label OR its raw numeric code
            def _candidate_matches(cand: str) -> bool:
                c = cand.strip().lower()
                for ni in normalized_issues:
                    if ni in c or c in ni:
                        return True
                    if c in _REVERSE_ISSUE_MAP.get(ni, []):  # e.g. "7101" matches "ideology"
                        return True
                return False
            row_issues = [c for c in candidates if _candidate_matches(c)]
        else:
            row_issues = candidates[:5]  # cap per-row to avoid explosion
        if not row_issues:
            continue
        participants = [c for c, code in code_lookup.items() if row.get('country_a_code') == code or row.get('country_b_code') == code]
        if not participants:
            continue
        decade = f"{int(row['year']) // 10 * 10}s"
        for issue in row_issues:
            key = issue.lower()
            if key not in issue_pool:
                issue_pool.append(key)
            label = issue  # preserve original capitalisation
            for country in participants:
                counts[country][label] += 1
                temporal[country][label][decade] += 1
            for li in range(len(participants)):
                for ri in range(li + 1, len(participants)):
                    agreement_edges[(participants[li], participants[ri], label)] += 1
            # Cross-country edge: any two selected countries both active on this issue
            for li in range(len(selected)):
                for ri in range(li + 1, len(selected)):
                    ca, cb = selected[li], selected[ri]
                    if counts[ca].get(label, 0) > 0 and counts[cb].get(label, 0) > 0:
                        agreement_edges[(ca, cb, label)] += 1

    # Limit displayed issues to top 15 most active; decode numeric codes → readable labels
    all_issue_counts: Counter = Counter()
    for c in counts.values():
        all_issue_counts.update(c)
    raw_display_issues = [i for i, _ in all_issue_counts.most_common(15)]

    def _readable(raw: str) -> str:
        decoded = _decode_issue_label(raw)
        if decoded == raw:
            # Not a numeric code — plain string from dataset; title-case it
            return raw.replace('_', ' ').title()
        return decoded

    # Map raw labels → readable (merges duplicates that decode to the same label)
    issue_rename: dict[str, str] = {raw: _readable(raw) for raw in raw_display_issues}
    display_issues = list(dict.fromkeys(issue_rename.values()))  # preserve order, deduplicate
    # Rebuild counts under decoded labels
    decoded_counts: dict[str, Counter] = {c: Counter() for c in selected}
    for country, cnt in counts.items():
        for raw, n in cnt.items():
            decoded_counts[country][issue_rename.get(raw, raw)] += n
    matrix = [{'country': country, **{issue: decoded_counts[country].get(issue, 0) for issue in display_issues}} for country in selected]
    rankings = {issue: [{'country': c, 'count': decoded_counts[c].get(issue, 0)} for c in sorted(selected, key=lambda n: decoded_counts[n].get(issue, 0), reverse=True)] for issue in display_issues}
    agreement_network = {
        'nodes': [{'id': c, 'group': profiles[c]['centrality']['degree']} for c in selected],
        'edges': [{'source': l, 'target': r, 'issue': _decode_issue_label(iss), 'weight': w} for (l, r, iss), w in agreement_edges.most_common(30)],
    }

    resolution_votes = []
    topic_stance: dict[str, dict] = {}  # per-country vote breakdown for selected topic

    if not votes_df.empty:
        subset = votes_df[votes_df['country_name'].isin(selected)]
        if topic:
            topic_subset = subset[subset['topic'].str.contains(topic, case=False, na=False)]
        else:
            topic_subset = subset
        for _, row in topic_subset.sort_values(['year', 'resolution'], ascending=[False, True]).head(200).iterrows():
            resolution_votes.append({'country': row['country_name'], 'year': int(row['year']), 'resolution': row['resolution'], 'topic': row['topic'], 'vote': row['vote']})

        # Topic voting stance: for each country, count yes/no/abstain on resolutions under this topic
        if topic and not topic_subset.empty:
            for country in selected:
                cdf = topic_subset[topic_subset['country_name'] == country]
                if cdf.empty:
                    topic_stance[country] = {'yes': 0, 'no': 0, 'abstain': 0, 'total': 0, 'pct_yes': 0}
                    continue
                vc = cdf['vote'].str.lower().value_counts().to_dict()
                yes = vc.get('yes', 0) + vc.get('y', 0)
                no = vc.get('no', 0) + vc.get('n', 0)
                abstain = vc.get('abstain', 0) + vc.get('a', 0)
                total = yes + no + abstain
                topic_stance[country] = {
                    'yes': yes, 'no': no, 'abstain': abstain, 'total': total,
                    'pct_yes': round(yes / total * 100, 1) if total else 0,
                }

    # Remap temporal keys to decoded display names (same as matrix/rankings)
    temporal_payload: dict = {}
    for c, imap in temporal.items():
        decoded_imap: dict = {}
        for raw_iss, decades in imap.items():
            display_iss = issue_rename.get(raw_iss, _readable(raw_iss))
            if display_iss not in decoded_imap:
                decoded_imap[display_iss] = {}
            for decade, val in decades.items():
                decoded_imap[display_iss][decade] = decoded_imap[display_iss].get(decade, 0) + val
        temporal_payload[c] = decoded_imap
    return {'countries': selected, 'issues': display_issues, 'matrix': matrix, 'agreement_network': agreement_network, 'rankings': rankings, 'temporal': temporal_payload, 'resolution_votes': resolution_votes, 'topic_stance': topic_stance, 'selected_topic': topic or ''}


def _timeline_payload(data: dict[str, Any], countries: list[str], metric: str) -> dict[str, Any]:
    profiles = data.get('country_profiles', {})
    series = []
    for country in countries[:5]:
        profile = profiles.get(country)
        if not profile:
            continue
        def _metric_val(item: dict) -> float:
            if metric == 'conflicts':
                return float(item.get('conflicts', 0))
            if metric == 'deaths':
                return float(item.get('deaths', 0) or 0)
            if metric == 'intensity':
                # Average lethality per conflict event — meaningfully different from raw deaths
                c = item.get('conflicts', 0) or 0
                d = item.get('deaths', 0) or 0
                return round(float(d) / float(c), 1) if c > 0 else 0.0
            return float(item.get(metric, 0) or 0)

        values = [{'year': item['year'], 'value': _metric_val(item)} for item in profile.get('timeline', [])]
        series.append({'country': country, 'values': values})

    master_df: pd.DataFrame = data.get('master_df', pd.DataFrame())
    global_deaths = []
    new_conflicts = []
    if not master_df.empty:
        grouped = master_df.groupby('year').agg(deaths=('deaths', 'sum'))
        seen_conflicts = set()
        for year, row in grouped.iterrows():
            global_deaths.append({'year': int(year), 'deaths': float(row['deaths']) if pd.notna(row['deaths']) else 0.0})
        by_year = master_df.sort_values('year')
        for year, group in by_year.groupby('year'):
            new_count = 0
            for name in group['conflict_name'].fillna(''):
                if name and name not in seen_conflicts:
                    seen_conflicts.add(name)
                    new_count += 1
            new_conflicts.append({'year': int(year), 'count': new_count})
    return {'series': series, 'global_deaths': global_deaths, 'new_conflicts': new_conflicts}


def _forecast_payload(data: dict[str, Any], countries: list[str], metric: str, horizon: int = 5) -> dict[str, Any]:
    profiles = data.get('country_profiles', {})
    forecasts = []
    for country in countries[:5]:
        profile = profiles.get(country)
        if not profile:
            continue
        timeline = profile.get('timeline', [])
        if len(timeline) < 4:
            continue
        years = np.array([item['year'] for item in timeline])
        def _fval(item: dict) -> float:
            if metric == 'intensity':
                c = item.get('conflicts', 0) or 0
                d = item.get('deaths', 0) or 0
                return float(d) / float(c) if c > 0 else 0.0
            return float(item.get(metric, item.get('conflicts', 0)) or 0)
        values = np.array([_fval(item) for item in timeline])
        # Use last 15 years for the trend fit to avoid over-weighting old data
        mask = years >= max(years) - 15
        fit_years, fit_values = years[mask], values[mask]
        if len(fit_years) < 3:
            fit_years, fit_values = years, values
        try:
            coeffs = np.polyfit(fit_years - fit_years[0], fit_values, 1)
        except Exception:
            continue
        future_years = np.arange(int(years[-1]) + 1, int(years[-1]) + horizon + 1)
        predicted = np.polyval(coeffs, future_years - fit_years[0])
        predicted = np.maximum(predicted, 0)  # no negative counts
        # Historical series for context
        history = [{'year': int(y), 'actual': float(v)} for y, v in zip(years[-20:], values[-20:])]
        forecast = [{'year': int(y), 'forecast': round(float(v), 1)} for y, v in zip(future_years, predicted)]
        trend = 'rising' if coeffs[0] > 0.1 else 'falling' if coeffs[0] < -0.1 else 'stable'
        forecasts.append({'country': country, 'metric': metric, 'trend': trend, 'history': history, 'forecast': forecast})
    return {'forecasts': forecasts, 'metric': metric}


def _dataset_progress(dataset_name: str, index: int, total: int) -> None:
    _set_progress(f'Loading {dataset_name} ({index}/{total})')


def _vote_only_mode() -> bool:
    discovered = set(discover_datasets().keys())
    return bool(discovered) and discovered.issubset(VOTE_DATASETS)


def _build_fresh_state() -> dict[str, Any]:
    ensure_directories()
    if _vote_only_mode():
        _set_progress('Preparing vote-only load')
    else:
        _set_progress('Parsing codebooks')
        build_codebook(force_rebuild=True)

    loaded = load_all_datasets(progress_callback=_dataset_progress)

    _set_progress('Building graph')
    graph_results = build_graphs(loaded.master_df, loaded.votes_df)

    _set_progress('Running ML analysis')
    ml_results = run_ml_analysis(graph_results['graph'], loaded.master_df, loaded.votes_df, graph_results['temporal_vote_stats'])

    _set_progress('Preparing API cache')
    country_profiles = _build_country_profiles(graph_results['graph_json'], loaded.master_df, loaded.votes_df, ml_results)
    countries = [{'name': profile['name'], 'gw_code': profile['gw_code']} for profile in sorted(country_profiles.values(), key=lambda item: item['name'])]

    payload = {
        'graph': graph_results['graph_json'],
        'graph_object': graph_results['graph'],
        'temporal_graphs': graph_results['temporal_graphs'],
        'countries': countries,
        'country_profiles': country_profiles,
        'country_similarity': ml_results['country_similarity'],
        'temporal_agreement': ml_results['temporal_agreement'],
        'alliance_blocs': ml_results['alliance_blocs'],
        'chord_data': ml_results['chord_data'],
        'embeddings_2d': ml_results['embeddings_2d'],
        'embeddings_3d': ml_results['embeddings_3d'],
        'datasets': loaded.dataset_summaries,
        'issues': loaded.issues_summary,
        'votes_df': loaded.votes_df,
        'master_df': loaded.master_df,
        'embedding_method': ml_results['embedding_method'],
    }

    with open(output_file('api_cache.json'), 'w', encoding='utf-8') as handle:
        json.dump({'datasets': loaded.dataset_summaries, 'issues': loaded.issues_summary, 'country_profiles': country_profiles, 'embedding_method': ml_results['embedding_method']}, handle, indent=2, ensure_ascii=False)

    _set_progress('Saving outputs')
    _save_runtime_cache(payload)
    return payload


def _load_or_build_state() -> dict[str, Any]:
    if _cache_is_fresh():
        _set_progress('Loading cache')
        return _load_runtime_cache()
    return _build_fresh_state()


def _pipeline_runner_sync() -> None:
    try:
        payload = _load_or_build_state()
        with state.lock:
            state.data = payload
            state.ready = True
            state.error = ''
            state.progress = 'Ready'
    except Exception as exc:
        with state.lock:
            state.ready = False
            state.progress = 'Failed'
            state.error = str(exc)


def _start_pipeline_thread() -> None:
    with state.lock:
        if state.thread and state.thread.is_alive():
            return
        state.ready = False
        state.error = ''
        state.progress = 'Queued'
        state.thread = threading.Thread(target=_pipeline_runner_sync, name='policy-stance-pipeline', daemon=True)
        state.thread.start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _start_pipeline_thread()
    yield


app = FastAPI(title='Geopolitical Intelligence System', version='1.0.0', description='Policy Stance Analyser backend', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.mount('/outputs', StaticFiles(directory=OUTPUTS_DIR), name='outputs')

# Serve built frontend — mount assets only; catch-all route is defined at end of file
_FRONTEND_DIST = Path(__file__).parent.parent / 'frontend' / 'dist'
if _FRONTEND_DIST.exists():
    app.mount('/assets', StaticFiles(directory=str(_FRONTEND_DIST / 'assets')), name='assets')


@app.get('/status')
def status() -> dict[str, Any]:
    graph = state.data.get('graph', {})
    progress = state.progress if not state.error else f"{state.progress}: {state.error}"
    return {'ready': state.ready, 'progress': progress, 'node_count': len(graph.get('nodes', [])), 'edge_count': len(graph.get('edges', [])), 'dataset_count': len(state.data.get('datasets', []))}


@app.get('/graph')
def graph() -> dict[str, Any]:
    return state.data.get('graph', {'nodes': [], 'edges': []})


@app.get('/graph/{year}')
def graph_by_year(year: int) -> dict[str, Any]:
    return state.data.get('temporal_graphs', {}).get(year, {'nodes': [], 'edges': []})


@app.get('/blocs-by-year/{year}')
def blocs_by_year(year: int) -> dict[str, Any]:
    """Compute country→bloc assignments using UN votes in a rolling window around `year`."""
    MANUAL_OVERRIDES = {'India': 'Non-Aligned', 'Sri Lanka': 'China-Centered Bloc'}
    BLOC_ANCHORS: dict[str, list[str]] = {
        'Western Bloc': ['USA', 'UK', 'France', 'Germany', 'Japan', 'Australia', 'Canada'],
        'Russia+Allies': ['Russia', 'Belarus', 'North Korea', 'Syria'],
        'China-Centered Bloc': ['China', 'Pakistan', 'Cambodia'],
        'Non-Aligned': ['Brazil', 'South Africa', 'Indonesia', 'Egypt'],
    }
    country_names = {p['name'] for p in state.data.get('countries', [])}
    votes_df: pd.DataFrame = state.data.get('votes_df', pd.DataFrame())

    def _static_fallback() -> dict[str, str]:
        raw = state.data.get('alliance_blocs', {}).get('country_to_bloc', {})
        return {k: MANUAL_OVERRIDES.get(k, v) for k, v in raw.items() if k in country_names}

    if votes_df.empty or 'year' not in votes_df.columns or 'country_name' not in votes_df.columns:
        return _static_fallback()

    # Rolling 7-year window; widen to 15 if too few rows
    window = votes_df[(votes_df['year'] >= year - 7) & (votes_df['year'] <= year)]
    if len(window) < 200:
        window = votes_df[votes_df['year'] <= year].tail(5000)

    vote_map = {'yes': 1, 'Y': 1, 'no': -1, 'N': -1, 'abstain': 0, 'A': 0}
    w = window.copy()
    w['v'] = w['vote'].map(vote_map).fillna(0)
    w = w[w['country_name'].isin(country_names)]
    if w.empty:
        return _static_fallback()

    pivot = w.pivot_table(index='country_name', columns='resolution', values='v', aggfunc='mean').fillna(0)

    # Build anchor centroids from countries present in this year's data
    anchor_vectors: dict[str, np.ndarray] = {}
    for bloc, anchors in BLOC_ANCHORS.items():
        present = [a for a in anchors if a in pivot.index]
        if present:
            vecs = pivot.loc[present].values.astype(float)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            vecs = vecs / np.where(norms > 0, norms, 1)
            anchor_vectors[bloc] = vecs.mean(axis=0)

    if len(anchor_vectors) < 2:
        return _static_fallback()

    def _cos(a: np.ndarray, b: np.ndarray) -> float:
        d = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(np.dot(a, b) / d) if d > 0 else 0.0

    c2b: dict[str, str] = {}
    for country in pivot.index:
        if country in MANUAL_OVERRIDES:
            c2b[country] = MANUAL_OVERRIDES[country]
            continue
        vec = pivot.loc[country].values.astype(float)
        scores = {bloc: _cos(vec, av) for bloc, av in anchor_vectors.items()}
        c2b[country] = max(scores, key=scores.get)

    # Fill countries absent from vote data with static fallback
    static = _static_fallback()
    for country in country_names:
        if country not in c2b:
            c2b[country] = static.get(country, 'Non-Aligned')

    return c2b


@app.get('/graph-delta/{year}')
def graph_delta(year: int) -> dict[str, Any]:
    graphs = state.data.get('temporal_graphs', {})
    cur = graphs.get(year, {'nodes': [], 'edges': []})
    prev = graphs.get(year - 1, {'nodes': [], 'edges': []})

    def norm(e) -> tuple[str, str]:
        s, t = str(e['source']), str(e['target'])
        return (min(s, t), max(s, t))

    cur_pairs = {norm(e) for e in cur.get('edges', [])}
    prev_pairs = {norm(e) for e in prev.get('edges', [])}
    cur_nodes = {str(n['id']) for n in cur.get('nodes', [])}
    prev_nodes = {str(n['id']) for n in prev.get('nodes', [])}

    new_pairs = cur_pairs - prev_pairs
    ended_pairs = prev_pairs - cur_pairs

    # Resolve node IDs to names for display
    id_to_name = {str(n['id']): n.get('name', n['id']) for n in cur.get('nodes', []) + prev.get('nodes', [])}

    def named(pair):
        return {'source': id_to_name.get(pair[0], pair[0]), 'target': id_to_name.get(pair[1], pair[1])}

    return {
        'year': year,
        'nodes': len(cur_nodes),
        'edges': len(cur_pairs),
        'new_edges': len(new_pairs),
        'ended_edges': len(ended_pairs),
        'new_nodes': len(cur_nodes - prev_nodes),
        'exited_nodes': len(prev_nodes - cur_nodes),
        'new_edge_names': [named(p) for p in list(new_pairs)[:80]],
        'ended_edge_names': [named(p) for p in list(ended_pairs)[:80]],
    }


@app.get('/countries')
def countries() -> list[dict[str, Any]]:
    return state.data.get('countries', [])


@app.get('/country/{name}')
def country(name: str) -> dict[str, Any]:
    for country_name, profile in state.data.get('country_profiles', {}).items():
        if country_name.lower() == name.lower():
            return profile
    raise HTTPException(status_code=404, detail='Country not found')


@app.get('/similarity')
def similarity() -> dict[str, Any]:
    raw = state.data.get('country_similarity', {'countries': [], 'matrix': []})
    # Filter to sovereign nations only to keep the matrix manageable
    country_names = {p['name'] for p in state.data.get('countries', [])}
    countries = raw.get('countries', [])
    matrix = raw.get('matrix', [])
    if not countries or not matrix:
        return raw
    indices = [i for i, c in enumerate(countries) if c in country_names]
    filtered_countries = [countries[i] for i in indices]
    filtered_matrix = [[matrix[r][c] for c in indices] for r in indices]
    return {'countries': filtered_countries, 'matrix': filtered_matrix}


@app.get('/temporal-agreement')
def temporal_agreement() -> dict[str, Any]:
    return state.data.get('temporal_agreement', {})


@app.get('/voting-agreement-matrix')
def voting_agreement_matrix() -> dict[str, Any]:
    """Pre-built NxN average vote agreement matrix for sovereign nations only."""
    ta = state.data.get('temporal_agreement', {})
    country_names = sorted({p['name'] for p in state.data.get('countries', [])})
    name_set = set(country_names)
    idx = {n: i for i, n in enumerate(country_names)}
    N = len(country_names)
    mat = [[0.5] * N for _ in range(N)]
    for i in range(N):
        mat[i][i] = 1.0
    for key, year_map in ta.items():
        parts = key.split('||') if '||' in key else key.split('-', 1)
        if len(parts) != 2:
            continue
        a, b = parts
        if a not in name_set or b not in name_set:
            continue
        i, j = idx[a], idx[b]
        if isinstance(year_map, dict):
            vals = [v for v in year_map.values() if isinstance(v, (int, float))]
        else:
            vals = [float(year_map)]
        if vals:
            avg = sum(vals) / len(vals)
            mat[i][j] = avg
            mat[j][i] = avg
    return {'countries': country_names, 'matrix': mat}


@app.get('/alliance-blocs')
def alliance_blocs() -> dict[str, Any]:
    MANUAL_OVERRIDES = {'India': 'Non-Aligned', 'Sri Lanka': 'China-Centered Bloc'}
    raw = state.data.get('alliance_blocs', {'country_to_bloc': {}, 'blocs': []})
    country_names = {p['name'] for p in state.data.get('countries', [])}
    c2b = {k: MANUAL_OVERRIDES.get(k, v) for k, v in raw.get('country_to_bloc', {}).items() if k in country_names}
    filtered_blocs = []
    for bloc in raw.get('blocs', []):
        bloc_label = bloc.get('label') or bloc.get('name', '')
        members = [m for m in bloc.get('members', []) if m in country_names and c2b.get(m) == bloc_label]
        if members:
            filtered_blocs.append({**bloc, 'members': members})
    return {'country_to_bloc': c2b, 'blocs': filtered_blocs}


@app.get('/chord')
def chord() -> dict[str, Any]:
    raw = state.data.get('chord_data', {'links': []})
    # Filter chord to real nation-states only (exclude non-state actors with synthetic codes)
    country_names = {p['name'] for p in state.data.get('countries', [])}
    filtered = [link for link in raw.get('links', []) if link.get('source') in country_names and link.get('target') in country_names]
    return {'links': filtered}


@app.get('/embeddings/2d')
def embeddings_2d() -> dict[str, Any]:
    # Only return embeddings for real nation-states
    country_names = {p['name'] for p in state.data.get('countries', [])}
    return {k: v for k, v in state.data.get('embeddings_2d', {}).items() if k in country_names}


@app.get('/embeddings/3d')
def embeddings_3d() -> dict[str, Any]:
    country_names = {p['name'] for p in state.data.get('countries', [])}
    return {k: v for k, v in state.data.get('embeddings_3d', {}).items() if k in country_names}


@app.get('/heatmap/{heatmap_type}')
def heatmap(heatmap_type: str):
    mapping = {
        'conflict_intensity': output_file('heatmap_conflict_intensity.png'),
        'un_voting': output_file('heatmap_un_voting.png'),
        'country_similarity': output_file('heatmap_country_similarity.png'),
    }
    path = mapping.get(heatmap_type)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail='Heatmap not found')
    return FileResponse(path, media_type='image/png')


@app.get('/forecast')
def forecast(countries: str = Query(''), metric: str = Query('conflicts'), horizon: int = Query(5)) -> dict[str, Any]:
    selected = [c.strip() for c in countries.split(',') if c.strip()]
    return _forecast_payload(state.data, selected, metric, horizon)


@app.get('/datasets')
def datasets() -> list[dict[str, Any]]:
    return state.data.get('datasets', [])


@app.get('/issues')
def issues() -> list[dict[str, Any]]:
    raw = state.data.get('issues', [])
    return [{'issue': _decode_issue_label(item['issue']), **{k: v for k, v in item.items() if k != 'issue'}} for item in raw]


@app.get('/compare')
def compare(country_a: str = Query(...), country_b: str = Query(...)) -> dict[str, Any]:
    return _compare_payload(state.data, country_a, country_b)


@app.get('/compare-insight')
def compare_insight(country_a: str = Query(...), country_b: str = Query(...)) -> dict[str, Any]:
    payload = _compare_payload(state.data, country_a, country_b)
    blocs = state.data.get('alliance_blocs', {}).get('country_to_bloc', {})
    a, b = payload['country_a'], payload['country_b']
    shared = payload['shared_conflicts']
    votes = payload['shared_votes']
    ta = payload['temporal_agreement']
    sim = payload['similarity']
    bloc_a = blocs.get(country_a, 'Unknown')
    bloc_b = blocs.get(country_b, 'Unknown')

    # Voting trend: early vs recent agreement
    if ta:
        years_sorted = sorted(ta.keys())
        early = [ta[y] for y in years_sorted[:5] if isinstance(ta[y], (int, float))]
        recent = [ta[y] for y in years_sorted[-5:] if isinstance(ta[y], (int, float))]
        early_avg = round(sum(early) / len(early) * 100, 1) if early else None
        recent_avg = round(sum(recent) / len(recent) * 100, 1) if recent else None
        if early_avg and recent_avg:
            drift = recent_avg - early_avg
            vote_trend = f"Vote agreement was {early_avg}% in the {''.join(years_sorted[:1])}s and is now {recent_avg}% — {'converging' if drift > 3 else 'diverging' if drift < -3 else 'stable'}."
        else:
            vote_trend = None
    else:
        early_avg = recent_avg = drift = vote_trend = None

    # Conflict summary
    if shared:
        peak_year = max(shared, key=lambda x: x.get('intensity', 0))
        conflict_summary = f"{len(shared)} shared conflict events; peak intensity in {peak_year['year']} ({peak_year['dataset']})."
        issues_seen = list({s['issue'] for s in shared if s.get('issue') and s['issue'] not in ('nan', '', 'None')})[:4]
    else:
        conflict_summary = "No direct conflict events recorded in the dataset."
        issues_seen = []

    # Bloc analysis
    same_bloc = bloc_a == bloc_b
    bloc_line = (f"Both are in the {bloc_a} — voting behaviour likely aligned." if same_bloc
                 else f"{country_a} aligns with the {bloc_a}; {country_b} with the {bloc_b} — structurally opposed blocs." if bloc_a != 'Non-Aligned' and bloc_b != 'Non-Aligned'
                 else f"Bloc divergence: {bloc_a} vs {bloc_b}.")

    # Relationship classification
    if sim > 0.75:
        rel_type = 'strong strategic alignment'
    elif sim > 0.5:
        rel_type = 'moderate alignment'
    elif sim > 0.25:
        rel_type = 'limited commonality'
    else:
        rel_type = 'structural divergence'

    # Votes match rate
    if votes:
        match_rate = round(sum(1 for v in votes if v['match']) / len(votes) * 100, 1)
        vote_line = f"On {len(votes)} sampled resolutions, they voted the same way {match_rate}% of the time."
    else:
        match_rate = None
        vote_line = "No overlapping UN voting record found."

    sentences = [
        f"{country_a} and {country_b} show {rel_type} (similarity score: {round(sim, 3)}).",
        bloc_line,
        conflict_summary,
    ]
    if vote_trend:
        sentences.append(vote_trend)
    sentences.append(vote_line)
    if issues_seen:
        sentences.append(f"Recurring conflict themes: {', '.join(issues_seen)}.")

    centrality_a = a.get('centrality', {})
    centrality_b = b.get('centrality', {})
    more_central = country_a if (centrality_a.get('pagerank', 0) > centrality_b.get('pagerank', 0)) else country_b
    sentences.append(f"{more_central} holds a more central position in the global conflict network by PageRank.")

    return {
        'insight': ' '.join(sentences),
        'bullets': sentences,
        'metrics': {
            'similarity': sim,
            'bloc_a': bloc_a,
            'bloc_b': bloc_b,
            'same_bloc': same_bloc,
            'shared_conflicts': len(shared),
            'vote_match_rate': match_rate,
            'early_vote_agreement': early_avg,
            'recent_vote_agreement': recent_avg,
            'vote_drift': drift if ta else None,
            'issues': issues_seen,
        },
    }


@app.get('/timeline')
def timeline(countries: str = Query(''), metric: str = Query('conflicts')) -> dict[str, Any]:
    selected = [item.strip() for item in countries.split(',') if item.strip()]
    return _timeline_payload(state.data, selected, metric)


@app.get('/policy-stance')
def policy_stance(countries: str = Query(''), issues: str = Query(''), topic: str | None = Query(None)) -> dict[str, Any]:
    selected_countries = [item.strip() for item in countries.split(',') if item.strip()]
    selected_issues = [item.strip() for item in issues.split(',') if item.strip()]
    return _policy_stance_payload(state.data, selected_countries, selected_issues, topic)


@app.get('/topics')
def topics() -> list[dict[str, Any]]:
    votes_df: pd.DataFrame = state.data.get('votes_df', pd.DataFrame())
    if votes_df.empty:
        return []
    counts = votes_df['topic'].value_counts().head(100)
    return [{'topic': topic, 'count': int(count)} for topic, count in counts.items()]


# Catch-all: serve frontend for any non-API path (must be LAST)
if _FRONTEND_DIST.exists():
    @app.get('/{full_path:path}', include_in_schema=False)
    def serve_frontend(full_path: str):
        from fastapi.responses import FileResponse
        return FileResponse(str(_FRONTEND_DIST / 'index.html'))
