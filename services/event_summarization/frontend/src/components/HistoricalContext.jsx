import { useEffect, useState } from "react";
import { getHistoricalContext } from "../api";

function Sparkline({ data }) {
  if (!data || data.length < 2) return null;
  const scores = data.map(d => d.score);
  const min = Math.min(...scores, -0.5);
  const max = Math.max(...scores, 0.5);
  const W = 200, H = 40;
  const x = (i) => (i / (data.length - 1)) * W;
  const y = (s) => H - ((s - min) / (max - min)) * H;
  const pts = data.map((d, i) => `${x(i).toFixed(1)},${y(d.score).toFixed(1)}`).join(" ");
  const zeroPct = ((0 - min) / (max - min)) * H;

  return (
    <svg width={W} height={H} style={{ overflow: "visible" }}>
      {/* Zero line */}
      <line x1={0} y1={H - zeroPct} x2={W} y2={H - zeroPct}
        stroke="var(--border-strong)" strokeWidth={0.5} strokeDasharray="2 2" />
      {/* Score line */}
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
      {/* Year labels */}
      <text x={0} y={H + 12} fill="var(--text-muted)" fontSize={9} fontFamily="monospace">
        {data[0]?.year}
      </text>
      <text x={W} y={H + 12} fill="var(--text-muted)" fontSize={9} fontFamily="monospace"
        textAnchor="end">
        {data[data.length - 1]?.year}
      </text>
    </svg>
  );
}

export default function HistoricalContext({ cc1, cc2 }) {
  const [ctx, setCtx]     = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!cc1 || !cc2 || cc1 === cc2) return;
    setLoading(true);
    setError("");
    setCtx(null);
    getHistoricalContext(cc1, cc2)
      .then(setCtx)
      .catch(e => {
        if (e.message?.includes("503")) setError("GGE database not loaded on server");
        else if (e.message?.includes("404")) setError("");  // no data for this pair — silent
        else setError(e.message);
      })
      .finally(() => setLoading(false));
  }, [cc1, cc2]);

  if (loading) return (
    <div className="hist-ctx hist-ctx-loading">
      <span className="scan-spinner">◉</span> Loading historical context…
    </div>
  );

  if (error) return (
    <div className="hist-ctx hist-ctx-warn">{error}</div>
  );

  if (!ctx) return null;

  const trendColor = ctx.trend === "improving" ? "var(--coop)" :
                     ctx.trend === "deteriorating" ? "var(--conflict)" : "var(--text-muted)";
  const trendArrow = ctx.trend === "improving" ? "↑" :
                     ctx.trend === "deteriorating" ? "↓" : "→";
  const avgColor   = ctx.avg_10yr >= 0.1 ? "var(--coop-text)" :
                     ctx.avg_10yr <= -0.1 ? "var(--conflict-text)" : "var(--text-secondary)";

  return (
    <div className="hist-ctx">
      <div className="hist-ctx-header">
        <span className="hist-ctx-label">📚 GGE HISTORICAL CONTEXT</span>
        <span className="hist-ctx-years">{ctx.earliest_year}–{ctx.latest_year}</span>
      </div>

      <p className="hist-ctx-summary">{ctx.summary}</p>

      <div className="hist-ctx-stats">
        <div className="hist-ctx-stat">
          <div className="hist-ctx-val" style={{ color: avgColor }}>
            {ctx.avg_10yr >= 0 ? "+" : ""}{ctx.avg_10yr.toFixed(3)}
          </div>
          <div className="hist-ctx-stat-label">10-yr avg</div>
        </div>
        <div className="hist-ctx-stat">
          <div className="hist-ctx-val" style={{ color: avgColor }}>
            {ctx.latest_static >= 0 ? "+" : ""}{ctx.latest_static.toFixed(3)}
          </div>
          <div className="hist-ctx-stat-label">{ctx.latest_year_val || ctx.latest_year} score</div>
        </div>
        <div className="hist-ctx-stat">
          <div className="hist-ctx-val" style={{ color: trendColor }}>
            {trendArrow} {ctx.trend}
          </div>
          <div className="hist-ctx-stat-label">trend</div>
        </div>
        <div className="hist-ctx-sparkline">
          <Sparkline data={ctx.sparkline} />
        </div>
      </div>

      <div className="hist-ctx-source">
        Source: Fan (2025) Global Geopolitical Events Database · scores normalized −1 to +1
      </div>
    </div>
  );
}
