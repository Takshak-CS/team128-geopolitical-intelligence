import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

function stabilityLabel(score) {
  if (score >= 3)  return { label: "Stable", color: "#4fae8a", desc: "Cooperative signals dominate domestic events — low internal tension." };
  if (score >= 0)  return { label: "Mixed",  color: "#e8a838", desc: "Some cooperative signals but tension indicators present. Monitor." };
  if (score >= -3) return { label: "Tense",  color: "#d6604f", desc: "Conflictual signals dominate — elevated internal tension." };
  return             { label: "Volatile", color: "#8b0000",  desc: "High domestic conflict — protests, coercion, or violence recorded." };
}

function eventDomainLabel(type) {
  const coopTypes = ["Consultation","Verbal Cooperation","Material Cooperation",
                     "Diplomatic Cooperation","Mediation","Provision of Aid","Yield / Concession","Engagement"];
  const pressTypes = ["Demand","Disapprove","Reject","Investigation"];
  const escTypes   = ["Threaten","Protest","Exhibit Force","Reduce Relations"];
  const confTypes  = ["Coerce","Assault","Fight","Mass Violence"];
  if (coopTypes.includes(type))  return "Political Cooperation";
  if (pressTypes.includes(type)) return "Political Pressure";
  if (escTypes.includes(type))   return "Escalation";
  if (confTypes.includes(type))  return "Conflict / Violence";
  return "Other";
}

const DOMAIN_COLORS = {
  "Political Cooperation": "#4fae8a",
  "Political Pressure":    "#e8a838",
  "Escalation":            "#d6604f",
  "Conflict / Violence":   "#8b0000",
  "Other":                 "#6e92a3",
};

export default function DomesticPanel({ domestic, countryName }) {
  if (!domestic) return null;
  const { total, avg_goldstein, event_type_counts } = domestic;

  if (total === 0) {
    return (
      <div className="domestic-empty">
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-muted)" }}>
          No domestic events recorded for {countryName} on this date.
          All events were cross-border international interactions.
        </div>
      </div>
    );
  }

  const stability = stabilityLabel(avg_goldstein);

  // Group event types by domain for the chart
  const domainCounts = {};
  Object.entries(event_type_counts).forEach(([type, count]) => {
    const domain = eventDomainLabel(type);
    domainCounts[domain] = (domainCounts[domain] || 0) + count;
  });
  const chartData = Object.entries(domainCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({ name, value }));

  // Top raw event types
  const topTypes = Object.entries(event_type_counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  return (
    <div className="domestic-panel">
      {/* Stability header */}
      <div className="domestic-stability" style={{ borderColor: stability.color }}>
        <div className="domestic-stability-left">
          <div className="domestic-stability-label" style={{ color: stability.color }}>
            DOMESTIC STABILITY: {stability.label.toUpperCase()}
          </div>
          <div className="domestic-stability-desc">{stability.desc}</div>
          <div className="domestic-stability-note">
            Based on {total.toLocaleString()} internal events · avg Goldstein {avg_goldstein >= 0 ? "+" : ""}{avg_goldstein.toFixed(2)}
          </div>
        </div>
        <div className="domestic-stability-score" style={{ color: stability.color }}>
          {avg_goldstein >= 0 ? "+" : ""}{avg_goldstein.toFixed(2)}
        </div>
      </div>

      {/* Domain breakdown */}
      <div className="domestic-section-label">Internal event domains</div>
      <div className="domestic-chart">
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid horizontal={false} stroke="#28404c" />
            <XAxis type="number" tick={{ fill: "#5c7480", fontSize: 10 }} />
            <YAxis type="category" dataKey="name" width={160} tick={{ fill: "#93acb7", fontSize: 11 }} />
            <Tooltip contentStyle={{ background: "#1c2f39", border: "1px solid #3a5562", borderRadius: 6, fontSize: 11 }}
              cursor={{ fill: "rgba(232,118,60,0.06)" }} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}
              fill="#6e92a3"
              label={false}
              isAnimationActive={true}
              cell={chartData.map(d => ({ fill: DOMAIN_COLORS[d.name] || "#6e92a3" }))}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Top event types */}
      <div className="domestic-section-label">Most frequent internal event types</div>
      <div className="domestic-types">
        {topTypes.map(([type, count]) => {
          const domain = eventDomainLabel(type);
          const color  = DOMAIN_COLORS[domain] || "#6e92a3";
          return (
            <div key={type} className="domestic-type-row">
              <span className="legend-dot" style={{ background: color, flexShrink: 0 }} />
              <span className="domestic-type-name">{type}</span>
              <span className="domestic-type-count" style={{ color }}>{count}</span>
            </div>
          );
        })}
      </div>

      {/* Data limitation note */}
      <div className="domestic-limitation">
        ℹ GDELT often captures internal events using city names or role labels (Police, Judge, Students)
        as actor proxies. These reflect real domestic activity but with limited actor-level resolution.
        The domain breakdown above is the most reliable signal from this data.
      </div>
    </div>
  );
}
