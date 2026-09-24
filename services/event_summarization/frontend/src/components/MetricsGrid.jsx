import InfoTip from "./InfoTip.jsx";

export default function MetricsGrid({ metrics }) {
  if (!metrics) return null;

  const gs = metrics.avg_goldstein;
  const gsColor = gs >= 1 ? "#4fae8a" : gs <= -1 ? "#d6604f" : "#6e92a3";
  const gsLabel = gs >= 1 ? "cooperative" : gs <= -1 ? "conflictual" : "neutral";

  const initiator = metrics.initiator_pct;
  const initiatorColor = initiator > 60 ? "#e8763c" : initiator < 40 ? "#7ec8ff" : "#a78bfa";

  return (
    <section>
      <p className="section-label">02 · At a glance</p>
      <div className="metrics-grid">

        {/* Events */}
        <div className="metric-card" style={{
          background: "linear-gradient(135deg, #1a2535 0%, #1e2d40 100%)",
          borderTop: "3px solid #7ec8ff",
        }}>
          <div className="metric-icon">📡</div>
          <div className="metric-value" style={{ color: "#7ec8ff" }}>
            {metrics.total_events.toLocaleString()}
          </div>
          <div className="metric-label">Events recorded</div>
          <div className="metric-sub">news reports matched to this country</div>
        </div>

        {/* Goldstein */}
        <div className="metric-card" style={{
          background: `linear-gradient(135deg, #1a2535 0%, #1e2d40 100%)`,
          borderTop: `3px solid ${gsColor}`,
        }}>
          <div className="metric-icon">{gs >= 1 ? "🤝" : gs <= -1 ? "⚡" : "⚖️"}</div>
          <div className="metric-value" style={{ color: gsColor }}>
            {gs >= 0 ? "+" : ""}{gs.toFixed(2)}
          </div>
          <div className="metric-label">
            Average Goldstein
            <InfoTip>
              A score from −10 (most conflictual) to +10 (most cooperative),
              assigned by political scientists to every event type.
              This is the average across all of today's events.
            </InfoTip>
          </div>
          <div className="metric-sub" style={{ color: gsColor }}>
            overall tone: {gsLabel}
          </div>
        </div>

        {/* Initiator */}
        <div className="metric-card" style={{
          background: "linear-gradient(135deg, #1a2535 0%, #1e2d40 100%)",
          borderTop: `3px solid ${initiatorColor}`,
        }}>
          <div className="metric-icon">🎯</div>
          <div className="metric-value" style={{ color: initiatorColor }}>
            {initiator}%
          </div>
          <div className="metric-label">Initiator role</div>
          <div className="metric-sub">
            {initiator > 60
              ? "mostly driving interactions"
              : initiator < 40
              ? "mostly receiving interactions"
              : "balanced initiator/recipient"}
          </div>
        </div>

        {/* Ambiguous */}
        <div className="metric-card" style={{
          background: "linear-gradient(135deg, #1a2535 0%, #1e2d40 100%)",
          borderTop: metrics.ambiguous_count > 0 ? "3px solid #e8a838" : "3px solid var(--border-strong)",
        }}>
          <div className="metric-icon">🔍</div>
          <div className="metric-value" style={{
            color: metrics.ambiguous_count > 0 ? "#e8a838" : "var(--text-secondary)"
          }}>
            {metrics.ambiguous_count}
          </div>
          <div className="metric-label">
            Signal conflicts
            <InfoTip>
              Events where the AI sentiment model disagreed with the
              Goldstein score — a quick cross-check, not an error.
              0 means either full agreement or sentiment is inactive.
            </InfoTip>
          </div>
          <div className="metric-sub">
            {metrics.ambiguous_count > 0
              ? "events flagged for review"
              : "no conflicts detected"}
          </div>
        </div>

      </div>
    </section>
  );
}
