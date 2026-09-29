import { useState, useCallback } from "react";
import ArticleScan from "./ArticleScan.jsx";
import InfoTip from "./InfoTip.jsx";

// ── Adjective → country name (mirrors backend _ACTOR_FIXES) ─────────
const ACTOR_NORM = {
  "Israeli": "Israel", "Palestinian": "Palestine", "Iranian": "Iran",
  "Iraqi": "Iraq", "Syrian": "Syria", "Yemeni": "Yemen",
  "Saudi": "Saudi Arabia", "Bahraini": "Bahrain", "Emirati": "UAE",
  "Qatari": "Qatar", "Kuwaiti": "Kuwait", "Omani": "Oman",
  "Jordanian": "Jordan", "Lebanese": "Lebanon", "Egyptian": "Egypt",
  "Turkish": "Turkey", "Afghan": "Afghanistan", "Pakistani": "Pakistan",
  "Indian": "India", "Nigerian": "Nigeria", "Kenyan": "Kenya",
  "Ugandan": "Uganda", "Ghanaian": "Ghana", "French": "France",
  "German": "Germany", "Spanish": "Spain", "British": "United Kingdom",
  "Australian": "Australia", "Canadian": "Canada", "Brazilian": "Brazil",
  "Mexican": "Mexico", "Russian": "Russia", "Chinese": "China",
  "Japanese": "Japan", "American": "United States",
  "Us": "United States", "U.S.": "United States", "U. S.": "United States",
  "Uk": "United Kingdom", "Kingdom": "Saudi Arabia",
};
function normActor(name) {
  if (!name) return name;
  return ACTOR_NORM[name.trim()] || name;
}

// ── Known city proxies (GDELT uses city names when actor is unresolved) ─
const CITY_CONTEXT = {
  "Antwerp": "a Belgian city — GDELT uses city names as actor proxies when the specific organisation or individual cannot be identified",
  "Gent": "Ghent, a Belgian city — used as an actor proxy by GDELT",
  "Brussels": "Belgium's capital — used as an actor proxy when the specific actor is unresolved",
  "Liege": "a Belgian city used as an actor proxy",
  "Amsterdam": "a Dutch city used as an actor proxy",
  "Rotterdam": "a Dutch city used as an actor proxy",
  "Munich": "a German city used as an actor proxy",
  "Hamburg": "a German city used as an actor proxy",
  "Lyon": "a French city used as an actor proxy",
  "Milan": "an Italian city used as an actor proxy",
  "Barcelona": "a Spanish city used as an actor proxy",
  "Dubai": "a UAE emirate used as an actor proxy",
  "Delhi": "India's capital region used as an actor proxy",
  "Mumbai": "an Indian city used as an actor proxy",
  "Karachi": "a Pakistani city used as an actor proxy",
  "Lagos": "a Nigerian city used as an actor proxy",
};

// ── Event type → readable verb ────────────────────────────────────────
const VERBS = {
  "Fight":                  "engaged in active fighting with",
  "Assault":                "carried out an assault on",
  "Mass Violence":          "was implicated in mass violence involving",
  "Coerce":                 "applied coercive pressure on",
  "Threaten":               "issued a threat against",
  "Exhibit Force":          "demonstrated a show of force against",
  "Reduce Relations":       "moved to reduce diplomatic relations with",
  "Protest":                "staged a protest against",
  "Disapprove":             "publicly condemned",
  "Reject":                 "rejected a proposal from",
  "Demand":                 "issued a formal demand toward",
  "Investigation":          "launched an investigation involving",
  "Verbal Cooperation":     "engaged in verbal cooperation with",
  "Material Cooperation":   "provided material cooperation to",
  "Diplomatic Cooperation": "entered into diplomatic cooperation with",
  "Consultation":           "held consultations with",
  "Mediation":              "attempted to mediate in a dispute involving",
  "Provision of Aid":       "extended aid to",
  "Yield / Concession":     "made a significant concession toward",
  "Engagement":             "engaged diplomatically with",
};

// ── What the score means in plain English ─────────────────────────────
function scoreMeaning(score) {
  if (score <= -8) return "maximum conflict — this is the most severe category of violence or hostility";
  if (score <= -5) return "severe conflict — active fighting or serious aggression";
  if (score <= -2) return "significant tension — hostile action taken";
  if (score < 0)   return "mild tension — adversarial but non-violent";
  if (score === 0) return "neutral — no clear cooperative or conflictual signal";
  if (score < 3)   return "mildly cooperative — routine diplomatic engagement";
  if (score < 7)   return "cooperative — constructive diplomatic action";
  return "strongly cooperative — a major positive diplomatic development";
}

// ── Core explanation sentence ─────────────────────────────────────────
function buildExplanation(row, clickedActor, countryName) {
  const a1    = normActor(row.Actor1Name) || "an actor";
  const a2    = normActor(row.Actor2Name) || "another party";
  const score = parseFloat(row.GoldsteinScale) || 0;
  const type  = row.EventType || "event";
  const role  = row.CountryRole || "";
  const verb  = VERBS[type] || "was involved in an event with";

  // Framed as GDELT's classification, not a narrated fact — this line
  // shows before any article is ever checked, so "Toronto carried out an
  // assault on China" reads as something that definitely happened when
  // it's really just raw, unverified GDELT coding (which is known to
  // miscode things like sports coverage as violent conflict).
  // Same actor on both sides ("Israel engaged in fighting with Israel")
  // reads as nonsense — describe it as a domestic event instead.
  const sameActor = a1.trim().toLowerCase() === a2.trim().toLowerCase();
  const actionLine = sameActor
    ? `Domestic event within ${a1.trim()}.`
    : `GDELT classified this as: ${a1} ${verb} ${a2}.`;

  // What it means
  const meaningLine = `Category: "${type}" — ${scoreMeaning(score)} (Goldstein: ${score >= 0 ? "+" : ""}${score.toFixed(1)}).`;

  // Country's role
  const roleLine =
    role === "Initiator"
      ? `${countryName} is recorded as the initiating party.`
      : role === "Recipient"
      ? `${countryName} is recorded as on the receiving end.`
      : `Both sides are recorded as active participants.`;

  // Article count signal
  const articles = parseInt(row.NumArticles) || 0;
  const coverageLine =
    articles >= 100 ? `Reported across ${articles} sources.` :
    articles >= 20  ? `Covered by ${articles} news outlets.` :
    articles >= 5   ? `${articles} sources recorded this event.` : "";

  return [actionLine, meaningLine, roleLine, coverageLine].filter(Boolean).join(" ");
}

// ── Helpers ───────────────────────────────────────────────────────────
function toneClass(score) {
  if (score >= 1) return "coop";
  if (score <= -1) return "conflict";
  return "neutral";
}
function classLabel(score) {
  if (score >= 5)  return "COOPERATIVE";
  if (score >= 1)  return "COOPERATIVE";
  if (score <= -5) return "CONFLICT";
  if (score <= -1) return "CONFLICT";
  return "NEUTRAL";
}
function ScoreBar({ score }) {
  const pct = (Math.min(Math.abs(score) / 10, 1) * 50).toFixed(1) + "%";
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
function sourceDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return null; }
}

const GENERIC_LABELS = new Set([
  "School","Police","Military","Government","Court","Student","Judge",
  "Rebels","Business","Media","Criminal","Officials","Authorities",
  "Protesters","Civilians","Workers","Teachers","Students"
]);

// ── Component ─────────────────────────────────────────────────────────
export default function ActorExplorer({ actor, tableRows, countryName, date, onClear }) {
  const [showAll, setShowAll] = useState(false);

  // url -> relevance link reported by each card's ArticleScan; used to
  // flag / optionally hide events whose article names neither actor.
  const [links, setLinks] = useState({});
  const [hideMistagged, setHideMistagged] = useState(false);
  const onRelevance = useCallback((url, link) => {
    setLinks((m) => (m[url] === link ? m : { ...m, [url]: link }));
  }, []);

  if (!actor) {
    return (
      <section>
        <p className="section-label">
          04 · Event explorer
          <InfoTip>Click any node in the network graph above to explore all events involving that actor on this date.</InfoTip>
        </p>
        <div className="actor-explorer-empty">
          <div className="actor-explorer-icon">↑</div>
          <div className="actor-explorer-prompt">
            Click any node in the network graph to explore their events
          </div>
        </div>
      </section>
    );
  }

  // Raw events involving this actor
  const rawEvents = (tableRows || []).filter(r =>
    r.Actor1Name === actor.id || r.Actor2Name === actor.id ||
    normActor(r.Actor1Name) === actor.id || normActor(r.Actor2Name) === actor.id
  );
  // Deduplicate: same actor pair + event type + score = same real-world event, keep most-covered
  const seen = {};
  const events = rawEvents
    .sort((a, b) => (parseInt(b.NumArticles) || 0) - (parseInt(a.NumArticles) || 0))
    .filter(r => {
      const key = [normActor(r.Actor1Name), normActor(r.Actor2Name), r.EventType, parseFloat(r.GoldsteinScale).toFixed(1)].join("|");
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    });
  const scores    = events.map(r => parseFloat(r.GoldsteinScale) || 0);
  const avgScore  = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  const initiator = events.filter(r => r.Actor1Name === actor.id).length;
  const recipient = events.filter(r => r.Actor2Name === actor.id).length;
  const typeCounts = {};
  events.forEach(r => { if (r.EventType) typeCounts[r.EventType] = (typeCounts[r.EventType] || 0) + 1; });
  const topTypes  = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const toneC     = avgScore >= 1 ? "#4fae8a" : avgScore <= -1 ? "#d6604f" : "#6e92a3";
  const displayed = showAll ? events : events.slice(0, 5);

  return (
    <section>
      <p className="section-label">04 · Event explorer</p>

      {/* Actor header */}
      <div className="actor-header">
        <div className="actor-header-left">
          <div className="actor-header-name">{normActor(actor.id)}</div>
          {CITY_CONTEXT[actor.id] && (
            <div className="actor-generic-note">
              📍 {actor.id} is {CITY_CONTEXT[actor.id]}
            </div>
          )}
          {GENERIC_LABELS.has(actor.id) && (
            <div className="actor-generic-note">
              ⚠ "{actor.id}" is a GDELT role label — the event cards below show what specifically occurred
            </div>
          )}
          <div className="actor-header-meta">
            <span style={{ color: toneC, fontFamily: "var(--font-mono)", fontSize: 13 }}>
              {events.length} events · avg {avgScore >= 0 ? "+" : ""}{avgScore.toFixed(1)} Goldstein
            </span>
            <span className="dos-tag">initiator in {initiator}</span>
            <span className="dos-tag">recipient in {recipient}</span>
            {topTypes.map(([t, n]) => <span key={t} className="dos-tag">{t} ({n})</span>)}
          </div>
        </div>
        <button className="actor-clear-btn" onClick={onClear}>✕ Clear</button>
      </div>

      {/* Event cards */}
      {(() => {
        const n = displayed.filter((r) => links[r.SOURCEURL] === "none").length;
        if (n === 0) return null;
        return (
          <div className="mistag-summary">
            {n} of {displayed.length} events look unrelated to this tag
            <button className="relevance-more" onClick={() => setHideMistagged((h) => !h)}>
              {hideMistagged ? "Show them" : "Hide them"}
            </button>
          </div>
        );
      })()}
      <div className="dos-feed">
        {displayed.map((row, i) => {
          const score   = parseFloat(row.GoldsteinScale) || 0;
          const tone    = toneClass(score);
          const label   = classLabel(score);
          const url     = row.SOURCEURL?.startsWith("http") ? row.SOURCEURL : null;
          const domain  = url ? sourceDomain(url) : null;
          const explanation = buildExplanation(row, actor.id, countryName);
          const mistagged = links[row.SOURCEURL] === "none";
          if (mistagged && hideMistagged) return null;

          return (
            <article key={row.SOURCEURL || `${row.Actor1Name}-${row.Actor2Name}-${row.SQLDATE}-${i}`} className={`dos-card ${tone}${mistagged ? " dos-card-mistagged" : ""}`}>
              {/* Header */}
              <div className="dos-header">
                <span className="dos-case">EVENT-{String(i+1).padStart(3,"0")} · {row.SQLDATE}</span>
                <span className={`dos-stamp ${tone}`}>{label}</span>
                <span className="dos-tag">{row.EventType}</span>
                {parseInt(row.NumArticles) > 0 && (
                  <span className="dos-tag">{row.NumArticles} articles</span>
                )}
                {mistagged && <span className="dos-tag mistag-badge">Likely mis-tagged by GDELT</span>}
                <span className={`dos-score ${tone}`}>
                  {score >= 0 ? "+" : ""}{score.toFixed(1)}
                </span>
              </div>

              {/* Actors */}
              <div className="dos-actors">
                <span className="dos-actor">{normActor(row.Actor1Name) || "—"}</span>
                <span className="dos-arrow">→</span>
                <span className="dos-actor">{normActor(row.Actor2Name) || "—"}</span>
              </div>

              {/* Score bar */}
              <ScoreBar score={score} />

              {/* ── THE KEY THING: always-visible plain English explanation ── */}
              <p className="event-explanation">{explanation}</p>

              {/* Article scan adds real headline on top when available */}
              {url && (
                <ArticleScan
                  url={url}
                  actor1={row.Actor1Name || ""}
                  actor2={row.Actor2Name || ""}
                  eventType={row.EventType || ""}
                  country={countryName}
                  score={score}
                  numArticles={parseInt(row.NumArticles) || 0}
                  role={row.CountryRole || ""}
                  cluster={row.EventCluster || ""}
                  autoLoad={true}
                  loadDelay={i * 600}
                  highlightTerm={actor.id}
                  onRelevance={onRelevance}
                />
              )}

              {/* Footer tags */}
              <div className="dos-meta">
                <span className="dos-tag">{row.CountryRole}</span>
                {row.EventCluster && <span className="dos-tag">{row.EventCluster}</span>}
                {url && (
                  <a className="dos-source" href={url} target="_blank" rel="noreferrer">
                    {domain ? `${domain} →` : "source →"}
                  </a>
                )}
              </div>
            </article>
          );
        })}
      </div>

      {events.length > 5 && (
        <button className="actor-show-more" onClick={() => setShowAll(s => !s)}>
          {showAll ? "Show fewer" : `Show all ${events.length} events →`}
        </button>
      )}
    </section>
  );
}
