import { useState, useEffect, useCallback, useMemo } from "react";

const SLIDES = [
  { key: "title",   label: "Overview"         },
  { key: "metrics", label: "By the numbers"   },
  { key: "events",  label: "Top events"       },
  { key: "map",     label: "Partners/Actors"  },
  { key: "outlook", label: "Outlook"          },
];

const VERBS = {
  "Fight": "engaged in active fighting with",
  "Assault": "carried out an assault involving",
  "Mass Violence": "was implicated in mass violence affecting",
  "Coerce": "applied coercive pressure on",
  "Threaten": "issued a threat directed at",
  "Exhibit Force": "demonstrated a show of force against",
  "Reduce Relations": "moved to reduce diplomatic relations with",
  "Protest": "staged a protest against",
  "Disapprove": "publicly disapproved of actions by",
  "Reject": "rejected a proposal from",
  "Demand": "issued a formal demand toward",
  "Verbal Cooperation": "engaged in verbal cooperation with",
  "Material Cooperation": "provided material cooperation to",
  "Diplomatic Cooperation": "entered into diplomatic cooperation with",
  "Consultation": "held consultations with",
  "Mediation": "attempted to mediate in a dispute involving",
  "Provision of Aid": "extended aid to",
  "Yield / Concession": "made a notable concession toward",
  "Engagement": "engaged diplomatically with",
};
const CONFLICT_TYPES = ["Fight", "Assault", "Coerce", "Threaten", "Protest", "Mass Violence"];
const COOP_TYPES = ["Consultation", "Verbal Cooperation", "Material Cooperation", "Diplomatic Cooperation", "Mediation"];

function formatDate(d) {
  if (!d || d.length !== 8) return d;
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${months[parseInt(d.slice(4,6))-1]} ${parseInt(d.slice(6,8))}, ${d.slice(0,4)}`;
}

function toneColor(score) {
  if (score >= 1)  return "#4fae8a";
  if (score <= -1) return "#d6604f";
  return "#6e92a3";
}

// Computes everything a slide needs directly from the scope-filtered row
// set, instead of relying on a single backend summary that mixed
// domestic and international events together. This is what makes the
// briefing actually respect the International/Domestic toggle.
function computeScopeStats(rows) {
  if (!rows || rows.length === 0) return null;

  const scores = rows.map(r => parseFloat(r.GoldsteinScale) || 0);
  const avg = scores.reduce((a, b) => a + b, 0) / rows.length;
  const initiatorCount = rows.filter(r => r.CountryRole === "Initiator").length;

  const typeCounts = {};
  const clusterCounts = {};
  rows.forEach(r => {
    const t = r.EventType || "Unknown";
    typeCounts[t] = (typeCounts[t] || 0) + 1;
    if (r.EventCluster) clusterCounts[r.EventCluster] = (clusterCounts[r.EventCluster] || 0) + 1;
  });
  const topType = Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0];
  const topCluster = Object.entries(clusterCounts).sort((a, b) => b[1] - a[1])[0];
  const topConflict = Object.entries(typeCounts).filter(([t]) => CONFLICT_TYPES.includes(t)).sort((a, b) => b[1] - a[1])[0];
  const topCoop = Object.entries(typeCounts).filter(([t]) => COOP_TYPES.includes(t)).sort((a, b) => b[1] - a[1])[0];

  // Most significant = largest absolute Goldstein score, either direction
  const topEvents = [...rows]
    .sort((a, b) => Math.abs(parseFloat(b.GoldsteinScale) || 0) - Math.abs(parseFloat(a.GoldsteinScale) || 0))
    .slice(0, 3);

  // Partner/actor breakdown — for international this is the other
  // country in each event; for domestic it's the other named actor.
  const counterparts = {};
  rows.forEach(r => {
    const label = r.Actor2CountryCode && r.Actor2CountryCode !== r.Actor1CountryCode
      ? (r.Actor2Name || r.Actor2CountryCode)
      : (r.Actor2Name || r.Actor1Name || "Unknown");
    if (!label) return;
    if (!counterparts[label]) counterparts[label] = { name: label, count: 0, scoreSum: 0 };
    counterparts[label].count += 1;
    counterparts[label].scoreSum += parseFloat(r.GoldsteinScale) || 0;
  });
  const topCounterparts = Object.values(counterparts)
    .map(c => ({ ...c, avg: c.scoreSum / c.count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);

  return {
    total: rows.length,
    avg,
    initiatorPct: Math.round((initiatorCount / rows.length) * 100),
    topType, topCluster, topConflict, topCoop,
    topEvents, topCounterparts,
  };
}

// ── Slides ────────────────────────────────────────────────────────────────

function TitleSlide({ result, scope, stats, otherTotal }) {
  const gs = stats ? stats.avg : 0;
  const tone = gs >= 1 ? "Cooperative" : gs <= -1 ? "Conflictual" : "Neutral";
  return (
    <div className="bm-slide bm-title">
      <div className="bm-eyebrow">
        GDELT PULSE · WIRE INTELLIGENCE · {scope === "domestic" ? "DOMESTIC VIEW" : "INTERNATIONAL VIEW"}
      </div>
      <h1 className="bm-country">{result.country_name.toUpperCase()}</h1>
      <div className="bm-date">{formatDate(result.date)}</div>
      {stats ? (
        <div className="bm-tone-pill" style={{
          background: toneColor(gs) + "22",
          border: `1px solid ${toneColor(gs)}`,
          color: toneColor(gs),
        }}>
          {tone} · avg {gs >= 0 ? "+" : ""}{gs.toFixed(2)} Goldstein · {stats.total} events
        </div>
      ) : (
        <div className="bm-tone-pill" style={{ color: "var(--text-muted)" }}>
          No {scope} events recorded on this date
        </div>
      )}
      {otherTotal > 0 && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
          {otherTotal} more {scope === "domestic" ? "international" : "domestic"} event{otherTotal === 1 ? "" : "s"} — toggle below
        </div>
      )}
    </div>
  );
}

function MetricsSlide({ stats }) {
  if (!stats) return <EmptySlide label="By the numbers" />;
  return (
    <div className="bm-slide bm-metrics">
      <div className="bm-slide-label">By the numbers</div>
      <div className="bm-stat-grid">
        <div className="bm-stat">
          <div className="bm-stat-val">{stats.total.toLocaleString()}</div>
          <div className="bm-stat-label">Events recorded</div>
        </div>
        <div className="bm-stat">
          <div className="bm-stat-val" style={{ color: toneColor(stats.avg) }}>
            {stats.avg >= 0 ? "+" : ""}{stats.avg.toFixed(2)}
          </div>
          <div className="bm-stat-label">Average Goldstein score</div>
        </div>
        <div className="bm-stat">
          <div className="bm-stat-val">{stats.initiatorPct}%</div>
          <div className="bm-stat-label">Initiator role</div>
        </div>
        {stats.topType && (
          <div className="bm-stat">
            <div className="bm-stat-val bm-stat-val-sm">{stats.topType[0]}</div>
            <div className="bm-stat-label">Dominant event type ({stats.topType[1]} events)</div>
          </div>
        )}
        {stats.topCluster && (
          <div className="bm-stat">
            <div className="bm-stat-val bm-stat-val-sm">{stats.topCluster[0]}</div>
            <div className="bm-stat-label">Primary activity cluster</div>
          </div>
        )}
      </div>
    </div>
  );
}

function EventsSlide({ stats, scope }) {
  if (!stats) return <EmptySlide label="Most significant events" />;
  return (
    <div className="bm-slide bm-events">
      <div className="bm-slide-label">Most significant events</div>
      {stats.topEvents.map((r, i) => {
        const score = parseFloat(r.GoldsteinScale) || 0;
        const verb = VERBS[r.EventType] || "was involved in an event with";
        return (
          <div key={i} className="bm-event-row" style={{ borderLeftColor: toneColor(score) }}>
            <div className="bm-event-score" style={{ color: toneColor(score) }}>
              {score >= 0 ? "+" : ""}{score.toFixed(1)}
            </div>
            <div className="bm-event-body">
              <div className="bm-event-actors">
                {r.Actor1Name || "—"}
                <span style={{ color: "var(--text-muted)", fontSize: 16, margin: "0 8px" }}>→</span>
                {r.Actor2Name || "—"}
                {scope === "domestic" && <span className="bm-domestic-tag">domestic</span>}
              </div>
              <div className="bm-event-type">{r.EventType} · {r.CountryRole}</div>
              <div className="bm-event-sentence">
                GDELT classified this as: {r.Actor1Name} {verb} {r.Actor2Name}.
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MapSlide({ stats, scope }) {
  if (!stats || stats.topCounterparts.length === 0) {
    return <EmptySlide label={scope === "domestic" ? "Domestic actors" : "Key partner countries"} />;
  }
  return (
    <div className="bm-slide bm-map-slide">
      <div className="bm-slide-label">
        {scope === "domestic" ? `Most active domestic actors` : `Key partner countries today`}
      </div>
      <div className="bm-partner-grid">
        {stats.topCounterparts.map((p) => (
          <div key={p.name} className="bm-partner" style={{ borderColor: toneColor(p.avg) }}>
            <div className="bm-partner-name">{p.name}</div>
            <div className="bm-partner-count" style={{ color: toneColor(p.avg) }}>
              {p.count} events · {p.avg >= 0 ? "+" : ""}{p.avg.toFixed(1)} Goldstein
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OutlookSlide({ stats, scope }) {
  if (!stats) return <EmptySlide label="Intelligence outlook" />;
  const gs = stats.avg;

  let headline, body;
  if (gs >= 3) {
    headline = "Stable and diplomatically active.";
    body = `Cooperative signals dominated${stats.topCoop ? `, led by ${stats.topCoop[0]}` : ""}. Low volatility, strong engagement.`;
  } else if (gs >= 0) {
    headline = "Mixed signals — monitor closely.";
    body = `The day showed a balance of cooperative${stats.topCoop ? ` (${stats.topCoop[0]})` : ""} and conflictual${stats.topConflict ? ` (${stats.topConflict[0]})` : ""} activity. Medium stability.`;
  } else {
    headline = "Turbulent and high-risk.";
    body = `Conflictual signals dominated${stats.topConflict ? `, primarily ${stats.topConflict[0]} events` : ""}. Elevated tension — the situation warrants close monitoring.`;
  }

  return (
    <div className="bm-slide bm-outlook">
      <div className="bm-slide-label">Intelligence outlook — {scope === "domestic" ? "domestic" : "international"}</div>
      <div className="bm-outlook-ring" style={{ borderColor: toneColor(gs) }}>
        <div className="bm-outlook-score" style={{ color: toneColor(gs) }}>
          {gs >= 0 ? "+" : ""}{gs.toFixed(2)}
        </div>
        <div className="bm-outlook-scale">Goldstein</div>
      </div>
      <div className="bm-outlook-headline">{headline}</div>
      <div className="bm-outlook-body">{body}</div>
      <div className="bm-outlook-footer">
        Powered by GDELT V1 · spaCy NER · KMeans Clustering · FastAPI · React
      </div>
    </div>
  );
}

function EmptySlide({ label }) {
  return (
    <div className="bm-slide">
      <div className="bm-slide-label">{label}</div>
      <p style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 14 }}>
        No events in this scope for this date.
      </p>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────

export default function BriefingMode({ result, internationalRows, domesticRows, initialScope, onClose }) {
  const [slide, setSlide]         = useState(0);
  const [animating, setAnimating] = useState(false);
  const [scope, setScope]         = useState(initialScope === "domestic" ? "domestic" : "international");

  const intlStats = useMemo(() => computeScopeStats(internationalRows), [internationalRows]);
  const domStats  = useMemo(() => computeScopeStats(domesticRows), [domesticRows]);
  const stats     = scope === "domestic" ? domStats : intlStats;
  const otherTotal = scope === "domestic" ? (internationalRows || []).length : (domesticRows || []).length;

  const go = useCallback((dir) => {
    if (animating) return;
    const next = slide + dir;
    if (next < 0 || next >= SLIDES.length) return;
    setAnimating(true);
    setTimeout(() => { setSlide(next); setAnimating(false); }, 220);
  }, [slide, animating]);

  useEffect(() => {
    const handler = (e) => {
      if (e.key === "ArrowRight" || e.key === " ") go(1);
      if (e.key === "ArrowLeft")  go(-1);
      if (e.key === "Escape")     onClose();
      if (e.key === "d" || e.key === "D") setScope(s => s === "domestic" ? "international" : "domestic");
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [go, onClose]);

  const slides = [
    <TitleSlide   result={result} scope={scope} stats={stats} otherTotal={otherTotal} />,
    <MetricsSlide stats={stats} />,
    <EventsSlide  stats={stats} scope={scope} />,
    <MapSlide     stats={stats} scope={scope} />,
    <OutlookSlide stats={stats} scope={scope} />,
  ];

  return (
    <div className="bm-overlay">
      <div className="bm-scope-toggle">
        <button
          className={`bm-scope-btn ${scope === "international" ? "active" : ""}`}
          onClick={() => setScope("international")}
        >
          🌍 International
        </button>
        <button
          className={`bm-scope-btn ${scope === "domestic" ? "active" : ""}`}
          onClick={() => setScope("domestic")}
        >
          🏠 Domestic
        </button>
      </div>

      <div className={`bm-content ${animating ? "bm-fade-out" : "bm-fade-in"}`}>
        {slides[slide]}
      </div>

      <div className="bm-nav">
        <button className="bm-nav-btn" onClick={() => go(-1)} disabled={slide === 0}>←</button>
        <div className="bm-dots">
          {SLIDES.map((s, i) => (
            <button key={s.key} className={`bm-dot ${i === slide ? "active" : ""}`}
              onClick={() => setSlide(i)} title={s.label} />
          ))}
        </div>
        <button className="bm-nav-btn" onClick={() => go(1)} disabled={slide === SLIDES.length - 1}>→</button>
        <button className="bm-close-btn" onClick={onClose}>✕ Exit</button>
      </div>
    </div>
  );
}
