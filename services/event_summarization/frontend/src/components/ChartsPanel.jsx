import InfoTip from "./InfoTip.jsx";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";

const COOP = "#4fae8a";
const CONFLICT = "#d6604f";
const NEUTRAL = "#6e92a3";
const ACCENT = "#e8763c";

function toneColor(label) {
  const l = label.toLowerCase();
  if (l.includes("strongly cooperative")) return COOP;
  if (l.includes("cooperative")) return "#7ecbac";
  if (l.includes("highly conflictual")) return CONFLICT;
  if (l.includes("tense")) return "#e68d80";
  return NEUTRAL;
}

function sentimentColor(label) {
  const l = label.toLowerCase();
  if (l === "positive") return COOP;
  if (l === "negative") return CONFLICT;
  return NEUTRAL;
}

function clusterColor(label) {
  const l = label.toLowerCase();
  if (l.includes("cooperation")) return COOP;
  if (l.includes("conflict") || l.includes("violence")) return CONFLICT;
  if (l.includes("pressure") || l.includes("escalation") || l.includes("protest"))
    return ACCENT;
  return NEUTRAL;
}

function toEntries(counts) {
  return Object.entries(counts || {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

function Donut({ title, counts, colorFn }) {
  const data = toEntries(counts);
  if (data.length === 0) return null;

  return (
    <div className="chart-card">
      <p className="chart-card-title">{title}</p>
      <ResponsiveContainer width="100%" height={140}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius={36}
            outerRadius={58}
            paddingAngle={2}
            stroke="none"
          >
            {data.map((entry, i) => (
              <Cell key={i} fill={colorFn(entry.name)} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: "#1c2f39",
              border: "1px solid #3a5562",
              borderRadius: 6,
              fontSize: 12,
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-legend">
        {data.map((d) => (
          <span key={d.name}>
            <span
              className="legend-dot"
              style={{ background: colorFn(d.name) }}
            />
            {d.name} — {d.value}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function ChartsPanel({
  eventTypeCounts,
  toneCounts,
  sentimentCounts,
  clusterCounts,
}) {
  const eventData = toEntries(eventTypeCounts).slice(0, 8);

  return (
    <section>
      <p className="section-label">03 · Event composition</p>
      <div className="charts-grid">
        <div className="chart-card">
          <p className="chart-card-title">
            Event types (CAMEO)
            <InfoTip>
              CAMEO is the coding system GDELT uses to classify every event
              into one of 20 categories, from "Verbal Cooperation" to "Mass
              Violence."
            </InfoTip>
          </p>
          <ResponsiveContainer width="100%" height={Math.max(eventData.length * 32, 160)}>
            <BarChart
              data={eventData}
              layout="vertical"
              margin={{ top: 0, right: 16, bottom: 0, left: 0 }}
            >
              <CartesianGrid horizontal={false} stroke="#28404c" />
              <XAxis type="number" tick={{ fill: "#5c7480", fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                width={150}
                tick={{ fill: "#93acb7", fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{
                  background: "#1c2f39",
                  border: "1px solid #3a5562",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                cursor={{ fill: "rgba(232,118,60,0.08)" }}
              />
              <Bar dataKey="value" fill={ACCENT} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="donut-row">
          <Donut title="Goldstein tone" counts={toneCounts} colorFn={toneColor} />
          <Donut
            title="AI sentiment"
            counts={sentimentCounts}
            colorFn={sentimentColor}
          />
          <Donut
            title={
              <>
                Event clusters
                <InfoTip>
                  Events grouped automatically by an algorithm (KMeans) based
                  on their type and score — it isn't told the category names
                  in advance, it finds the pattern itself.
                </InfoTip>
              </>
            }
            counts={clusterCounts}
            colorFn={clusterColor}
          />
        </div>
      </div>
    </section>
  );
}
