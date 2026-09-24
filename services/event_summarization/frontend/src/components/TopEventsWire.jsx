import ArticleScan from "./ArticleScan.jsx";
import InfoTip from "./InfoTip.jsx";

function toneClass(score) {
  if (score >= 1) return "coop";
  if (score <= -1) return "conflict";
  return "neutral";
}

function classificationLabel(score) {
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

function sourceDomain(url) {
  if (!url) return null;
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    // Shorten very long domains
    return host.length > 30 ? host.slice(0, 28) + "…" : host;
  } catch {
    return null;
  }
}

function formatDate(yyyymmdd) {
  if (!yyyymmdd || yyyymmdd.length !== 8) return yyyymmdd;
  return `${yyyymmdd.slice(0,4)}-${yyyymmdd.slice(4,6)}-${yyyymmdd.slice(6,8)}`;
}

export default function TopEventsWire({ events, countryName, date }) {
  if (!events || events.length === 0) return null;

  return (
    <section>
      <p className="section-label">
        04 · Most significant events
        <InfoTip>
          The 3 most conflictual and 2 most cooperative events of the day,
          ranked by how extreme their Goldstein score was.
          Each sentence is inferred from the CAMEO event code and actor data.
          Click the source to read the original news report.
        </InfoTip>
      </p>
      <div className="dos-feed">
        {events.map((e) => {
          const tone    = toneClass(e.score);
          const label   = classificationLabel(e.score);
          const domain  = sourceDomain(e.url);
          return (
            <article key={e.rank} className={`dos-card ${tone}`}>
              {/* Header row */}
              <div className="dos-header">
                <span className="dos-case">
                  WIRE-{String(e.rank).padStart(3,"0")} · {formatDate(date)}
                </span>
                <span className={`dos-stamp ${tone}`}>{label}</span>
                <span className="dos-tag">{e.event_type}</span>
                {typeof e.num_articles === "number" && e.num_articles > 0 && (
                  <span className="dos-tag">{e.num_articles} articles</span>
                )}
                <span className={`dos-score ${tone}`}>
                  {e.score >= 0 ? "+" : ""}{e.score.toFixed(1)}
                </span>
              </div>

              {/* Actors */}
              <div className="dos-actors">
                <span className="dos-actor">{e.actor1}</span>
                <span className="dos-arrow">→</span>
                <span className="dos-actor">{e.actor2}</span>
              </div>

              {/* Score bar */}
              <ScoreBar score={e.score} />

              {/* Article scan — auto-loads with stagger so cards don't all fire at once */}
              {e.url && (
                <ArticleScan
                  url={e.url}
                  actor1={e.actor1}
                  actor2={e.actor2}
                  eventType={e.event_type}
                  country={countryName}
                  score={e.score}
                  numArticles={e.num_articles}
                  role={e.role}
                  cluster={e.cluster}
                  autoLoad={true}
                  loadDelay={e.rank * 600}
                />
              )}

              {/* Footer */}
              <div className="dos-meta">
                <span className="dos-tag">{countryName}: {e.role}</span>
                {e.cluster && <span className="dos-tag">{e.cluster}</span>}
                {e.url && (
                  <a className="dos-source" href={e.url} target="_blank" rel="noreferrer">
                    {domain ? `${domain} →` : "read source →"}
                  </a>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
