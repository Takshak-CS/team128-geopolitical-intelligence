import streamlit as st
import pandas as pd
import plotly.express as px

from src.preprocess import (
    preprocess, get_top5_events, summarize, fetch_gdelt_file,
    get_cached_dates,
    NER_AVAILABLE, SENTIMENT_AVAILABLE, CLUSTER_AVAILABLE,
)
from src.utils import get_country_display_list, get_country_name

st.set_page_config(
    page_title="GDELT Video Intelligence",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS — lighter palette ────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

    /* Lighter dark background — was #0d1117 */
    .stApp { background-color: #161b27; color: #e2e8f0; }

    .hero-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #1a2f4e 60%, #162540 100%);
        border: 1px solid #3a6090; border-radius: 12px;
        padding: 1.8rem 2.5rem; margin-bottom: 1.5rem;
    }
    .hero-title { font-family:'Space Mono',monospace; font-size:1.9rem; font-weight:700; color:#7ec8ff; margin:0; }
    .hero-sub   { color:#a0b4c8; font-size:0.95rem; margin-top:0.4rem; }

    .pipeline-bar {
        display:flex; gap:0; margin:1.2rem 0; border-radius:8px;
        overflow:hidden; border:1px solid #3a6090;
    }
    .pipeline-step {
        flex:1; padding:0.55rem 0.4rem; font-size:0.68rem;
        font-family:'Space Mono',monospace; text-align:center;
        color:#7a9ab8; background:#1e2d40; border-right:1px solid #3a6090;
    }
    .pipeline-step.active { background:#1e3a5f; color:#7ec8ff; font-weight:700; }
    .pipeline-step.done   { background:#163328; color:#4caf7d; }
    .pipeline-step:last-child { border-right:none; }
    .pipeline-step.dim    { color:#445566; }

    .ml-status-bar { display:flex; gap:0.8rem; margin:0.8rem 0; flex-wrap:wrap; align-items:center; }
    .ml-badge { display:inline-flex; align-items:center; gap:0.4rem; padding:0.3rem 0.75rem;
                border-radius:6px; font-family:'Space Mono',monospace; font-size:0.7rem; }
    .ml-badge.on  { background:#163328; border:1px solid #4caf7d; color:#4caf7d; }
    .ml-badge.off { background:#252535; border:1px solid #555; color:#777; }

    /* Metric cards — lighter base */
    .metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:1rem; margin:1.5rem 0; }
    .metric-card { background:#1e2d40; border:1px solid #3a6090; border-radius:10px; padding:1.2rem; text-align:center; }
    .metric-value { font-family:'Space Mono',monospace; font-size:2rem; font-weight:700; color:#7ec8ff; }
    .metric-label { font-size:0.72rem; color:#7a9ab8; margin-top:0.3rem; text-transform:uppercase; letter-spacing:0.5px; }

    .section-header {
        font-family:'Space Mono',monospace; font-size:0.78rem; color:#7ec8ff;
        text-transform:uppercase; letter-spacing:2px;
        border-bottom:1px solid #3a6090; padding-bottom:0.5rem; margin:2rem 0 1rem 0;
    }

    /* Event cards */
    .event-card { background:#1e2d40; border:1px solid #3a6090; border-radius:10px; padding:1.1rem 1.3rem; margin-bottom:0.8rem; }
    .event-card.conflict { border-left:4px solid #e05a5a; }
    .event-card.coop     { border-left:4px solid #4caf7d; }
    .event-card.neutral  { border-left:4px solid #7a9ab8; }
    .event-rank       { font-family:'Space Mono',monospace; font-size:0.68rem; color:#7a9ab8; margin-bottom:0.4rem; }
    .event-actors     { font-size:1rem; font-weight:600; color:#e2e8f0; margin-bottom:0.2rem; }
    .event-actor-label{ font-size:0.68rem; color:#7a9ab8; font-family:'Space Mono',monospace; letter-spacing:1px; }
    .event-type-badge { display:inline-block; background:#1e3a5f; color:#7ec8ff; font-size:0.68rem;
        font-family:'Space Mono',monospace; padding:0.15rem 0.5rem; border-radius:4px; margin-right:0.4rem; }
    .score-badge-conflict { display:inline-block; background:#3d1e1e; color:#e05a5a; font-size:0.72rem;
        font-family:'Space Mono',monospace; font-weight:700; padding:0.15rem 0.6rem; border-radius:4px; }
    .score-badge-coop    { display:inline-block; background:#163328; color:#4caf7d; font-size:0.72rem;
        font-family:'Space Mono',monospace; font-weight:700; padding:0.15rem 0.6rem; border-radius:4px; }
    .score-badge-neutral { display:inline-block; background:#1e2d40; color:#7a9ab8; font-size:0.72rem;
        font-family:'Space Mono',monospace; font-weight:700; padding:0.15rem 0.6rem; border-radius:4px; }
    .bert-badge-pos { display:inline-block; background:#163328; color:#4caf7d; font-size:0.65rem;
        font-family:'Space Mono',monospace; padding:0.1rem 0.4rem; border-radius:4px; margin-left:0.3rem; }
    .bert-badge-neg { display:inline-block; background:#3d1e1e; color:#e05a5a; font-size:0.65rem;
        font-family:'Space Mono',monospace; padding:0.1rem 0.4rem; border-radius:4px; margin-left:0.3rem; }
    .bert-badge-amb { display:inline-block; background:#332800; color:#e8a838; font-size:0.65rem;
        font-family:'Space Mono',monospace; padding:0.1rem 0.4rem; border-radius:4px; margin-left:0.3rem; }
    .event-desc { color:#a0b4c8; font-size:0.85rem; margin-top:0.5rem; line-height:1.5; }
    .event-url  { font-size:0.72rem; margin-top:0.4rem; }

    /* Summary box */
    .summary-box {
        background: linear-gradient(135deg, #163328 0%, #1a2f4e 100%);
        border:1px solid #4caf7d; border-left:4px solid #4caf7d;
        border-radius:10px; padding:1.5rem 1.8rem;
        font-size:0.96rem; line-height:1.85; color:#d0dce8;
    }
    .summary-tag {
        display:inline-block; background:#163328; border:1px solid #4caf7d;
        color:#4caf7d; font-size:0.68rem; font-family:'Space Mono',monospace;
        padding:0.2rem 0.6rem; border-radius:4px; margin-bottom:1rem;
    }

    .raw-label { font-family:'Space Mono',monospace; font-size:0.72rem; color:#e8a838; margin-bottom:0.5rem; }
    .input-panel { background:#1e2d40; border:1px solid #3a6090; border-radius:10px; padding:1.4rem; margin-bottom:1.5rem; }

    /* Cache badge */
    .cache-pill {
        display:inline-block; background:#1e2d40; border:1px solid #3a6090;
        color:#7a9ab8; font-family:'Space Mono',monospace; font-size:0.65rem;
        padding:0.15rem 0.5rem; border-radius:10px; margin-right:0.3rem; margin-top:0.4rem;
    }

    /* Streamlit overrides */
    .stTextInput>div>div>input {
        background-color:#1e2d40!important; border:1px solid #3a6090!important;
        color:#e2e8f0!important; font-family:'Space Mono',monospace!important; border-radius:6px!important;
    }
    .stSelectbox>div>div {
        background-color:#1e2d40!important; border:1px solid #3a6090!important;
        color:#e2e8f0!important; border-radius:6px!important;
    }
    .stButton>button {
        background:#1f6feb!important; color:white!important; border:none!important;
        border-radius:6px!important; font-family:'Space Mono',monospace!important;
        font-weight:700!important; padding:0.5rem 2rem!important;
        font-size:0.85rem!important; letter-spacing:1px!important;
    }
    .stButton>button:hover { background:#4d96ff!important; }
    div[data-testid="stDataFrame"] { border:1px solid #3a6090; border-radius:8px; overflow:hidden; }
    label, .stSelectbox label, .stTextInput label {
        color:#a0b4c8!important; font-size:0.78rem!important;
        font-family:'Space Mono',monospace!important; letter-spacing:1px!important;
    }
</style>
""", unsafe_allow_html=True)

# ── HERO ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero-header">
    <div class="hero-title">🎬 GDELT Video Intelligence</div>
    <div class="hero-sub">ML-Enhanced Preprocessing Pipeline · Live GDELT Feed · Any Date · Any Country</div>
</div>
<div class="pipeline-bar">
    <div class="pipeline-step done">① FETCH</div>
    <div class="pipeline-step active">② FILTER</div>
    <div class="pipeline-step active">③ CLEAN</div>
    <div class="pipeline-step active">④ NER</div>
    <div class="pipeline-step active">⑤ SENTIMENT</div>
    <div class="pipeline-step active">⑥ CLUSTER</div>
    <div class="pipeline-step active">⑦ SUMMARIZE</div>
    <div class="pipeline-step dim">⑧ AI NARRATE</div>
    <div class="pipeline-step dim">⑨ VIDEO</div>
</div>
""", unsafe_allow_html=True)

# ── ML STATUS ─────────────────────────────────────────────────────────────────
ner_cls  = "on" if NER_AVAILABLE       else "off"
sent_cls = "on" if SENTIMENT_AVAILABLE else "off"
clus_cls = "on" if CLUSTER_AVAILABLE   else "off"
ner_txt  = "✓ spaCy NER"             if NER_AVAILABLE       else "✗ spaCy NER"
sent_txt = "✓ AI Sentiment"            if SENTIMENT_AVAILABLE else "✗ AI Sentiment"
clus_txt = "✓ KMeans Clustering"      if CLUSTER_AVAILABLE   else "✗ KMeans"

st.markdown(f"""
<div class="ml-status-bar">
    <span style="font-family:'Space Mono',monospace;font-size:0.7rem;color:#7a9ab8;display:flex;align-items:center;">ML LAYERS:</span>
    <span class="ml-badge {ner_cls}">{ner_txt}</span>
    <span class="ml-badge {sent_cls}">{sent_txt}</span>
    <span class="ml-badge {clus_cls}">{clus_txt}</span>
</div>
""", unsafe_allow_html=True)

if not (NER_AVAILABLE and SENTIMENT_AVAILABLE and CLUSTER_AVAILABLE):
    st.info("💡 To enable all ML features: `pip install spacy transformers torch scikit-learn && python -m spacy download en_core_web_sm`")

# ── CACHE STATUS ─────────────────────────────────────────────────────────────
cached = get_cached_dates()
if cached:
    pills = "".join([f'<span class="cache-pill">📁 {d}</span>' for d in reversed(cached)])
    st.markdown(
        f'<div style="margin-bottom:0.5rem;"><span style="font-family:\'Space Mono\',monospace;'
        f'font-size:0.68rem;color:#7a9ab8;">CACHED DATES (last 5): </span>{pills}</div>',
        unsafe_allow_html=True
    )

# ── INPUTS ────────────────────────────────────────────────────────────────────
st.markdown('<div class="input-panel">', unsafe_allow_html=True)
col1, col2, col3 = st.columns([1, 2, 1])

with col1:
    date = st.text_input("DATE (YYYYMMDD)", "20260327")

with col2:
    country_code = country_name = selected = None
    display_list = None
    if date and len(date) == 8 and date.isdigit():
        with st.spinner(f"📡 Fetching GDELT data for {date}..."):
            try:
                fetch_gdelt_file(date)
                display_list = get_country_display_list(date)
            except FileNotFoundError as e:
                st.error(f"❌ {e}")
            except Exception as e:
                st.warning(f"⚠️ Could not load data: {e}")
        if display_list:
            selected     = st.selectbox("COUNTRY", display_list)
            country_code = selected.split(" ")[0]
            country_name = get_country_name(country_code)
        elif display_list is not None:
            st.warning("⚠️ No recognised countries found in this file.")
    else:
        st.info("Enter a valid 8-digit date above.")

with col3:
    st.markdown("<br>", unsafe_allow_html=True)
    run = st.button("▶ RUN PIPELINE")

st.markdown('</div>', unsafe_allow_html=True)

# ── ANALYSIS ──────────────────────────────────────────────────────────────────
if run:
    if not country_code:
        st.error("Please select a valid country first.")
        st.stop()

    with st.spinner(f"⚙️ Running ML pipeline for {country_name} on {date}..."):
        try:
            df = preprocess(date, country_code)
        except FileNotFoundError as e:
            st.error(f"❌ {e}"); st.stop()
        except Exception as e:
            st.error(f"❌ Pipeline error: {e}"); st.stop()

    if df.empty:
        st.warning(f"⚠️ No events found for **{country_name} ({country_code})** on {date}.")
        st.stop()

    st.success(f"✅ Pipeline complete — **{len(df)} events** processed for **{country_name}** on {date}")

    # ── ① RAW DATA ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">① RAW DATA INGESTION — LIVE FROM GDELT</div>', unsafe_allow_html=True)
    st.markdown('<div class="raw-label">data.gdeltproject.org · tab-separated · no header · 58 columns · auto-downloaded & cached</div>', unsafe_allow_html=True)
    try:
        raw_df = pd.read_csv(f"data/{date}.export.CSV", sep="\t", header=None, low_memory=False, nrows=5)
        st.dataframe(raw_df, use_container_width=True, height=155)
    except Exception:
        st.info("Raw file preview unavailable.")

    # ── ② METRICS ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">② FILTERING & CLEANING RESULTS</div>', unsafe_allow_html=True)
    avg_score     = df["GoldsteinScale"].mean()
    initiator_pct = round((df["CountryRole"] == "Initiator").sum() / len(df) * 100)
    ambig_count   = int((df.get("SentimentAgreement", pd.Series(dtype=str)) == "⚠ Ambiguous").sum())

    st.markdown(f"""
    <div class="metric-grid">
        <div class="metric-card"><div class="metric-value">{len(df)}</div><div class="metric-label">Events Matched</div></div>
        <div class="metric-card"><div class="metric-value">{avg_score:+.2f}</div><div class="metric-label">Avg Goldstein</div></div>
        <div class="metric-card"><div class="metric-value">{initiator_pct}%</div><div class="metric-label">Initiator Role</div></div>
        <div class="metric-card"><div class="metric-value">{ambig_count}</div><div class="metric-label">Ambiguous (AI≠Goldstein)</div></div>
    </div>
    """, unsafe_allow_html=True)

    # ── ③ EVENT TYPE DISTRIBUTION ─────────────────────────────────────────
    st.markdown('<div class="section-header">③ EVENT TYPE DISTRIBUTION (CAMEO)</div>', unsafe_allow_html=True)
    event_counts = df["EventType"].value_counts().reset_index()
    event_counts.columns = ["EventType", "Count"]
    fig_bar = px.bar(event_counts, x="Count", y="EventType", orientation="h",
                     color="Count", color_continuous_scale=["#1e3a5f","#2d6bb0","#7ec8ff"],
                     template="plotly_dark")
    fig_bar.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans", color="#a0b4c8"), coloraxis_showscale=False,
        yaxis=dict(categoryorder="total ascending"),
        margin=dict(l=10,r=10,t=10,b=10), height=380,
    )
    fig_bar.update_traces(marker_line_width=0)
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── ④ TONE CHARTS ─────────────────────────────────────────────────────
    st.markdown('<div class="section-header">④ GEOPOLITICAL TONE · GOLDSTEIN + AI SENTIMENT</div>', unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns(3)

    tone_colors = {
        "strongly cooperative": "#4caf7d", "cooperative": "#69c98f",
        "neutral": "#7a9ab8", "tense": "#e8a838", "highly conflictual": "#e05a5a",
    }

    with col_a:
        fig_hist = px.histogram(df, x="GoldsteinScale", nbins=20,
                                color_discrete_sequence=["#2d6bb0"], template="plotly_dark")
        fig_hist.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="DM Sans", color="#a0b4c8"),
            margin=dict(l=10,r=10,t=30,b=10),
            title=dict(text="Goldstein Distribution", font=dict(color="#7ec8ff", size=13)),
            height=270,
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    with col_b:
        tone_counts = df["Tone"].value_counts().reset_index()
        tone_counts.columns = ["Tone", "Count"]
        fig_pie = px.pie(tone_counts, names="Tone", values="Count", color="Tone",
                         color_discrete_map=tone_colors, template="plotly_dark", hole=0.4)
        fig_pie.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", font=dict(family="DM Sans", color="#a0b4c8"),
            margin=dict(l=10,r=10,t=30,b=10),
            title=dict(text="Goldstein Tone", font=dict(color="#7ec8ff", size=13)),
            showlegend=True, legend=dict(font=dict(size=10)), height=270,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_c:
        if SENTIMENT_AVAILABLE and "SentimentLabel" in df.columns:
            sent_counts = df["SentimentLabel"].value_counts().reset_index()
            sent_counts.columns = ["Label", "Count"]
            sent_colors = {"Positive": "#4caf7d", "Negative": "#e05a5a", "Unknown": "#7a9ab8"}
            fig_sent = px.pie(sent_counts, names="Label", values="Count", color="Label",
                              color_discrete_map=sent_colors, template="plotly_dark", hole=0.4)
            fig_sent.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", font=dict(family="DM Sans", color="#a0b4c8"),
                margin=dict(l=10,r=10,t=30,b=10),
                title=dict(text="AI Sentiment", font=dict(color="#7ec8ff", size=13)),
                showlegend=True, legend=dict(font=dict(size=10)), height=270,
            )
            st.plotly_chart(fig_sent, use_container_width=True)
        else:
            st.info("AI Sentiment not available — run pip install transformers torch")

    # ── ⑤ KMEANS ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">⑤ ML EVENT CLUSTERING · KMEANS (EVENT TYPE × GOLDSTEIN)</div>', unsafe_allow_html=True)
    if CLUSTER_AVAILABLE and "EventCluster" in df.columns:
        col_cl1, col_cl2 = st.columns(2)
        with col_cl1:
            cluster_counts = df["EventCluster"].value_counts().reset_index()
            cluster_counts.columns = ["Cluster", "Count"]
            fig_cl = px.bar(cluster_counts, x="Cluster", y="Count",
                            color="Count", color_continuous_scale=["#1e3a5f","#2d6bb0","#7ec8ff"],
                            template="plotly_dark")
            fig_cl.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#a0b4c8"), coloraxis_showscale=False,
                margin=dict(l=10,r=10,t=10,b=10), height=260, xaxis_title="", yaxis_title="Events",
            )
            fig_cl.update_traces(marker_line_width=0)
            st.plotly_chart(fig_cl, use_container_width=True)

        with col_cl2:
            scatter_df = df.dropna(subset=["GoldsteinScale"]).copy()
            scatter_df["EventRootNum"] = pd.to_numeric(scatter_df["EventRootCode"], errors="coerce")
            fig_sc = px.scatter(scatter_df, x="EventRootNum", y="GoldsteinScale",
                                color="EventCluster", template="plotly_dark", opacity=0.7,
                                labels={"EventRootNum":"CAMEO Root Code","GoldsteinScale":"Goldstein Score"})
            fig_sc.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#a0b4c8"),
                margin=dict(l=10,r=10,t=10,b=10), height=260,
                legend=dict(font=dict(size=10), title_text="Cluster"),
            )
            st.plotly_chart(fig_sc, use_container_width=True)
    else:
        st.info("KMeans not available. Install scikit-learn to enable.")

    # ── ⑥ TOP 5 EVENTS ────────────────────────────────────────────────────
    st.markdown('<div class="section-header">⑥ TOP 5 MOST SIGNIFICANT EVENTS</div>', unsafe_allow_html=True)
    top5 = get_top5_events(df, country_name)

    if not top5:
        st.info("No events with Goldstein scores available.")
    else:
        for e in top5:
            score = e["score"]
            if score <= -1:   card_cls, score_cls, arrow = "event-card conflict", "score-badge-conflict", "🔴"
            elif score >= 1:  card_cls, score_cls, arrow = "event-card coop",     "score-badge-coop",     "🟢"
            else:             card_cls, score_cls, arrow = "event-card neutral",   "score-badge-neutral",  "⚪"

            sent = e.get("sentiment", "N/A")
            agr  = e.get("agreement", "N/A")
            if agr == "✓ Confirmed":
                bert_html = f'<span class="bert-badge-pos">Sentiment: {sent} ✓</span>'
            elif agr == "⚠ Ambiguous":
                bert_html = f'<span class="bert-badge-amb">Sentiment: {sent} ⚠</span>'
            else:
                bert_html = f'<span style="font-size:0.65rem;color:#555;margin-left:0.3rem;">Sentiment: N/A</span>'

            cluster_html = (f'<span class="event-type-badge">{e["cluster"]}</span>'
                            if e.get("cluster") else "")
            url_html = (f'<div class="event-url"><a href="{e["url"]}" target="_blank" '
                        f'style="color:#7ec8ff;font-size:0.72rem;">📰 Source article →</a></div>'
                        if e["url"] else "")

            st.markdown(f"""
            <div class="{card_cls}">
                <div class="event-rank">
                    EVENT #{e['rank']} &nbsp;·&nbsp; {e['event_type']}
                    &nbsp;·&nbsp; {arrow} GOLDSTEIN: <span class="{score_cls}">{score:+.1f}</span>
                    {bert_html}
                    &nbsp;·&nbsp; {country_name} role: <strong>{e['role']}</strong>
                </div>
                <div style="display:flex;gap:2rem;margin:0.5rem 0 0.4rem 0;flex-wrap:wrap;">
                    <div>
                        <div class="event-actor-label">ACTOR 1 (INITIATOR)</div>
                        <div class="event-actors">🔵 {e['actor1']}</div>
                    </div>
                    <div style="display:flex;align-items:center;color:#445566;font-size:1.2rem;">→</div>
                    <div>
                        <div class="event-actor-label">ACTOR 2 (RECIPIENT)</div>
                        <div class="event-actors">🟠 {e['actor2']}</div>
                    </div>
                    <div style="margin-left:auto;display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">
                        {cluster_html}
                        <span style="font-size:0.7rem;color:#7a9ab8;">{e['tone']}</span>
                    </div>
                </div>
                <div class="event-desc">{e['sentence'].replace('**','')}</div>
                {url_html}
            </div>
            """, unsafe_allow_html=True)

    # ── ⑦ ENRICHED TABLE ──────────────────────────────────────────────────
    st.markdown('<div class="section-header">⑦ CLEANED & ENRICHED DATASET WITH ML COLUMNS</div>', unsafe_allow_html=True)
    show_cols = ["SQLDATE","Actor1Name","Actor1CountryCode","Actor2Name","Actor2CountryCode",
                 "EventType","GoldsteinScale","Tone","CountryRole"]
    if SENTIMENT_AVAILABLE and "SentimentLabel" in df.columns:
        show_cols += ["SentimentLabel","SentimentScore","SentimentAgreement"]
    if CLUSTER_AVAILABLE and "EventCluster" in df.columns:
        show_cols += ["EventCluster"]

    display_df = df[show_cols].copy()
    display_df["Actor1Name"] = display_df["Actor1Name"].fillna("— (unspecified)")
    display_df["Actor2Name"] = display_df["Actor2Name"].fillna("— (unspecified)")
    display_df = display_df.rename(columns={
        "Actor1Name": "Actor 1", "Actor1CountryCode": "A1 Country",
        "Actor2Name": "Actor 2", "Actor2CountryCode": "A2 Country",
        "CountryRole": f"{country_code} Role",
        "SentimentLabel": "AI Sentiment", "SentimentScore": "Confidence",
        "SentimentAgreement": "Agreement", "EventCluster": "Cluster",
    })
    st.dataframe(display_df.head(25), use_container_width=True, height=340)

    # ── ⑧ NARRATION SUMMARY ───────────────────────────────────────────────
    st.markdown('<div class="section-header">⑧ AUTO-GENERATED NARRATION SEED · ML-INFORMED</div>', unsafe_allow_html=True)
    summary_text = summarize(df, country_name, date, top5)
    st.markdown('<div class="summary-box"><div class="summary-tag">🎙 NARRATION SCRIPT PREVIEW</div>', unsafe_allow_html=True)
    st.markdown(summary_text)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("""
    <br>
    <div style="background:#1e2d40;border:1px dashed #3a6090;border-radius:8px;padding:1rem;
                color:#7a9ab8;font-size:0.8rem;font-family:'Space Mono',monospace;">
        NEXT STAGES (Phase 3) &nbsp;→&nbsp;
        <span style="color:#7ec8ff">Claude API</span> refines narration
        &nbsp;→&nbsp; <span style="color:#7ec8ff">ElevenLabs / gTTS</span> voiceover
        &nbsp;→&nbsp; <span style="color:#7ec8ff">FFmpeg + GDELT imagery</span> video brief
    </div>
    """, unsafe_allow_html=True)

else:
    st.markdown("""
    <div style="text-align:center;padding:4rem 0;">
        <div style="font-size:3rem">🌐</div>
        <div style="font-family:'Space Mono',monospace;font-size:0.9rem;margin-top:1rem;color:#a0b4c8;">
            ENTER ANY DATE FROM 2013 ONWARDS · SELECT COUNTRY · RUN PIPELINE
        </div>
        <div style="font-family:'Space Mono',monospace;font-size:0.72rem;margin-top:0.8rem;color:#5a7a9a;">
            NER · SENTIMENT · CLUSTERING · AUTO-DOWNLOAD · LIVE GDELT FEED
        </div>
    </div>
    """, unsafe_allow_html=True)
