import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { analyze } from "../api";

function fmt(yyyymmdd) {
  return `${yyyymmdd.slice(4,6)}/${yyyymmdd.slice(6,8)}`;
}

export default function TrendChart({ countryCode, countryName, cachedDates, currentDate }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!countryCode || cachedDates.length < 2) return;

    setLoading(true);
    const dates = [...cachedDates].sort();

    Promise.allSettled(
      dates.map(d => analyze(d, countryCode).then(r => ({
        date: fmt(d),
        rawDate: d,
        goldstein: parseFloat(r.metrics.avg_goldstein.toFixed(2)),
        events: r.metrics.total_events,
      })))
    ).then(results => {
      const points = results
        .filter(r => r.status === "fulfilled")
        .map(r => r.value);
      setData(points);
      setLoading(false);
    });
  }, [countryCode, cachedDates]);

  if (cachedDates.length < 2 || data.length < 2) return null;

  return (
    <section>
      <p className="section-label">00 · Goldstein trend — all cached dates</p>
      <div className="chart-card">
        <p className="chart-card-title">
          Average Goldstein score for {countryName} across {cachedDates.length} cached dates
          {loading && <span style={{color:"var(--text-muted)",marginLeft:8}}>loading…</span>}
        </p>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data} margin={{top:8,right:16,bottom:0,left:0}}>
            <CartesianGrid stroke="#28404c" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{fill:"#5c7480",fontSize:11}} />
            <YAxis domain={[-10,10]} tick={{fill:"#5c7480",fontSize:11}} />
            <ReferenceLine y={0} stroke="#3a5562" strokeWidth={1.5} />
            <Tooltip
              contentStyle={{background:"#1c2f39",border:"1px solid #3a5562",borderRadius:6,fontSize:12}}
              formatter={(v,n,p) => [`${v > 0 ? "+" : ""}${v}  (${p.payload.events?.toLocaleString()} events)`, "Goldstein"]}
            />
            <Line
              type="monotone"
              dataKey="goldstein"
              stroke="#e8763c"
              strokeWidth={2}
              dot={{fill:"#e8763c",r:4,stroke:"#15242c",strokeWidth:2}}
              activeDot={{r:6}}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
