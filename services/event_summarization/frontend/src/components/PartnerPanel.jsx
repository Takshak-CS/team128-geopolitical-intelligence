import HistoricalContext from "./HistoricalContext.jsx";
import ArticleScan from "./ArticleScan.jsx";
import { analyze } from "../api";

function inferSentence(row) {
  const a1 = row.Actor1Name || row.Actor1CountryCode || "an actor";
  const a2 = row.Actor2Name || row.Actor2CountryCode || "another party";
  const score = parseFloat(row.GoldsteinScale) || 0;
  const type = row.EventType || "event";
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
  const verb = VERBS[type] || "was involved in an event with";
  // Framed as GDELT's classification, not narrated fact — this shows
  // before any article is checked, so dramatic phrasing here ("one of
  // the most alarming incidents") for what might be a GDELT miscoding
  // (e.g. sports coverage tagged as violence) is actively misleading.
  const severity =
    score <= -8 ? "GDELT's most severe conflict category" :
    score <= -5 ? "GDELT's severe conflict category" :
    score <= -1 ? "a tense-development category" :
    score >= 8  ? "GDELT's strongly cooperative category" :
    score >= 4  ? "a positive-diplomatic-step category" :
    score >= 1  ? "a cooperative-exchange category" : "a neutral-exchange category";
  return `GDELT classified this as ${severity}: ${a1} ${verb} ${a2}.`;
}

// Analyses the mix of events between two countries and generates
// an intelligence assessment of what the pattern implies geopolitically.
function buildRelationshipIntel(events, countryName, partnerName, avgGoldstein) {
  if (!events || events.length === 0) return null;

  const scores = events.map(e => parseFloat(e.GoldsteinScale) || 0).filter(s => !isNaN(s));
  if (scores.length === 0) return null;

  const conflictEvents = scores.filter(s => s <= -5);
  const coopEvents    = scores.filter(s => s >= 5);
  const neutralEvents = scores.filter(s => s > -5 && s < 5);
  const maxConflict   = Math.min(...scores);
  const maxCoop       = Math.max(...scores);

  const types = events.map(e => e.EventType).filter(Boolean);
  const hasViolence    = types.some(t => ["Fight","Assault","Mass Violence","Coerce"].includes(t));
  const hasDiplomacy   = types.some(t => ["Consultation","Mediation","Diplomatic Cooperation","Yield / Concession","Material Cooperation"].includes(t));
  const hasProtests    = types.some(t => ["Protest","Disapprove","Reject","Demand"].includes(t));

  let pattern = "";
  let significance = "";
  let watchLevel = "";

  // Detect the relationship pattern
  if (conflictEvents.length > 0 && coopEvents.length > 0) {
    // Mixed — conflict AND cooperation simultaneously
    pattern = "conflict with parallel diplomacy";
    significance = `Both active fighting (score ${maxConflict.toFixed(1)}) and diplomatic cooperation (score +${maxCoop.toFixed(1)}) are occurring simultaneously. This pattern is characteristic of an active territorial or political dispute where violence continues while negotiations proceed in parallel — a fragile situation.`;
    watchLevel = "HIGH";
  } else if (conflictEvents.length >= Math.ceil(events.length * 0.6)) {
    // Predominantly conflict
    pattern = "predominantly adversarial";
    significance = `The majority of events between ${countryName} and ${partnerName} are conflictual${hasViolence ? ", including active violence" : ""}. This indicates a stressed bilateral relationship. Average Goldstein of ${avgGoldstein.toFixed(1)} confirms net-negative signals.`;
    watchLevel = "HIGH";
  } else if (coopEvents.length >= Math.ceil(events.length * 0.6)) {
    // Predominantly cooperative
    pattern = "predominantly cooperative";
    significance = `Relations between ${countryName} and ${partnerName} on this date were largely constructive${hasDiplomacy ? ", driven by diplomatic engagement" : ""}. Average Goldstein of +${avgGoldstein.toFixed(1)} reflects a positive bilateral dynamic.`;
    watchLevel = "LOW";
  } else if (hasProtests && !hasViolence) {
    // Protest-driven tension
    pattern = "diplomatic tension";
    significance = `The relationship shows diplomatic friction — demands, disapproval, or protests — without active violence. This may indicate a political dispute or policy disagreement that has not yet escalated to physical conflict.`;
    watchLevel = "MEDIUM";
  } else {
    // Neutral / routine
    pattern = "routine engagement";
    significance = `Relations appear largely routine on this date, with no dominant conflict or cooperation signal. Average Goldstein of ${avgGoldstein >= 0 ? "+" : ""}${avgGoldstein.toFixed(1)} suggests a neutral diplomatic baseline.`;
    watchLevel = "LOW";
  }

  const watchColors = { HIGH: "#d6604f", MEDIUM: "#e8a838", LOW: "#4fae8a" };

  return { pattern, significance, watchLevel, watchColor: watchColors[watchLevel] };
}

function sourceDomain(url) {
  if (!url) return null;
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host.length > 30 ? host.slice(0, 28) + "..." : host;
  } catch { return null; }
}
import { useState } from "react";

function toneColor(score) {
  if (score >= 1)  return "#4fae8a";
  if (score <= -1) return "#d6604f";
  return "#6e92a3";
}

function classification(score) {
  if (score >= 5)  return "COOPERATIVE";
  if (score >= 1)  return "COOPERATIVE";
  if (score <= -5) return "CONFLICT";
  if (score <= -1) return "CONFLICT";
  return "NEUTRAL";
}

function ScoreBar({ score }) {
  const abs = Math.min(Math.abs(score) / 10, 1);
  const pct = (abs * 50).toFixed(1) + "%";
  const color = score >= 1 ? "#1a7a52" : score <= -1 ? "#c0392b" : "var(--border-strong)";
  return (
    <div className="dos-bar-track">
      <div className="dos-bar-center" />
      {score !== 0 && (
        <div className="dos-bar-fill"
          style={{ [score >= 0 ? "left" : "right"]: "50%", width: pct, background: color }} />
      )}
    </div>
  );
}

export default function PartnerPanel({ partner, tableRows, date, countryCode, countryName, onClose, onRunAnalysis }) {
  const [running, setRunning]   = useState(false);
  const [partnerResult, setPartnerResult] = useState(null);
  const [error, setError]       = useState("");

  // Filter table rows to events involving this partner
  const events = (tableRows || []).filter(
    (r) =>
      r.Actor1CountryCode === partner.code ||
      r.Actor2CountryCode === partner.code
  ).slice(0, 10);

  const handleRunAnalysis = () => {
    setRunning(true);
    setError("");
    analyze(date, partner.code)
      .then((r) => { setPartnerResult(r); onRunAnalysis && onRunAnalysis(r); })
      .catch((e) => setError(e.message))
      .finally(() => setRunning(false));
  };

  const tone = partner.avg_goldstein >= 1
    ? "cooperative" : partner.avg_goldstein <= -1 ? "conflictual" : "neutral";
  const color = toneColor(partner.avg_goldstein);

  return (
    <div className="partner-panel">
      <div className="partner-panel-header">
        <div>
          <div className="partner-panel-eyebrow">
            Events involving both countries on this date
          </div>
          <div className="partner-panel-title">
            {countryName} <span style={{color:"var(--text-muted)",fontWeight:400,fontSize:22}}>↔</span> {partner.name}
          </div>
          <div className="partner-panel-meta">
            <span style={{ color, fontFamily: "var(--font-mono)", fontSize: 13 }}>
              {partner.count} shared events
            </span>
            <span className="tag" style={{ borderColor: color, color }}>{tone}</span>
            <span className="tag">
              avg Goldstein {partner.avg_goldstein >= 0 ? "+" : ""}{partner.avg_goldstein.toFixed(1)}
            </span>
          </div>
          <div style={{
            fontFamily:"var(--font-mono)",fontSize:11,color:"var(--text-muted)",marginTop:8
          }}>
            Showing events from {countryName}'s dataset where {partner.name} appears as a partner
          </div>
        </div>
        <button className="partner-panel-close" onClick={onClose}>✕</button>
      </div>

      <HistoricalContext cc1={partner.code} cc2={countryCode} />
      <div className="partner-panel-body">
        {/* Intelligence assessment — generated from event pattern */}
        {(() => {
          const intel = buildRelationshipIntel(events, countryName, partner.name, partner.avg_goldstein);
          if (!intel) return null;
          return (
            <div className="intel-assessment">
              <div className="intel-assessment-header">
                <span className="intel-pattern">{intel.pattern.toUpperCase()}</span>
                <span className="intel-watch" style={{ color: intel.watchColor, borderColor: intel.watchColor }}>
                  {intel.watchLevel} WATCH
                </span>
              </div>
              <p className="intel-significance">{intel.significance}</p>
              <div className="intel-bar">
                {events.map((e, i) => {
                  const s = parseFloat(e.GoldsteinScale) || 0;
                  const c = s >= 1 ? "#4fae8a" : s <= -1 ? "#d6604f" : "#6e92a3";
                  return <span key={i} className="intel-bar-block" style={{ background: c }} title={`${s >= 0 ? "+" : ""}${s.toFixed(1)}`} />;
                })}
              </div>
              <div className="intel-bar-legend">
                <span style={{color:"#d6604f"}}>■ conflictual</span>
                <span style={{color:"#6e92a3"}}>■ neutral</span>
                <span style={{color:"#4fae8a"}}>■ cooperative</span>
              </div>
            </div>
          );
        })()}

        {events.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
            No detailed event records available for this pair.
          </p>
        ) : (
          <div className="dos-feed">
            {events.map((row, i) => {
              const score = parseFloat(row.GoldsteinScale) || 0;
              const tone  = score >= 1 ? "coop" : score <= -1 ? "conflict" : "neutral";
              const label = classification(score);
              return (
                <article key={row.SOURCEURL || `${row.Actor1Name}-${row.Actor2Name}-${row.SQLDATE}-${i}`} className={`dos-card ${tone}`}>
                  <div className="dos-header">
                    <span className="dos-case">EVENT-{String(i + 1).padStart(3, "0")} · {row.SQLDATE}</span>
                    <span className={`dos-stamp ${tone}`}>{label}</span>
                    <span className="dos-tag">{row.EventType}</span>
                    <span className={`dos-score ${tone}`}>
                      {score >= 0 ? "+" : ""}{score.toFixed(1)}
                    </span>
                  </div>
                  <div className="dos-actors">
                    <span className="dos-actor">{row.Actor1Name || row.Actor1CountryCode || "—"}</span>
                    <span className="dos-arrow">→</span>
                    <span className="dos-actor">{row.Actor2Name || row.Actor2CountryCode || "—"}</span>
                  </div>
                  <ScoreBar score={score} />
                  <p className="event-explanation">{inferSentence(row)}</p>
                  {row.SOURCEURL && row.SOURCEURL.startsWith("http") && (
                    <ArticleScan
                      url={row.SOURCEURL}
                      actor1={row.Actor1Name || row.Actor1CountryCode || "an actor"}
                      actor2={row.Actor2Name || row.Actor2CountryCode || "another party"}
                      eventType={row.EventType}
                      country={countryName}
                      score={parseFloat(row.GoldsteinScale) || 0}
                      autoLoad={true}
                      loadDelay={i * 600}
                    />
                  )}
                  <div className="dos-meta">
                    <span className="dos-tag">{row.CountryRole}</span>
                    {row.EventCluster && <span className="dos-tag">{row.EventCluster}</span>}
                    {row.SOURCEURL && row.SOURCEURL.startsWith("http") && (
                      <a className="dos-source" href={row.SOURCEURL} target="_blank" rel="noreferrer">
                        {sourceDomain(row.SOURCEURL) ? `${sourceDomain(row.SOURCEURL)} →` : "source →"}
                      </a>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <div className="partner-panel-actions">
          {error && <p style={{ color: "#d6604f", fontSize: 12, fontFamily: "var(--font-mono)" }}>{error}</p>}
          <button
            className="run-button"
            onClick={handleRunAnalysis}
            disabled={running}
            style={{ fontSize: 13, padding: "10px 18px" }}
          >
            {running
              ? "Loading…"
              : `Run full analysis for ${partner.name}`}
          </button>
          <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            Runs the complete pipeline for {partner.name} on {date}
          </span>
        </div>
      </div>
    </div>
  );
}
