function formatDate(yyyymmdd) {
  if (!yyyymmdd || yyyymmdd.length !== 8) return yyyymmdd;
  return new Date(`${yyyymmdd.slice(0,4)}-${yyyymmdd.slice(4,6)}-${yyyymmdd.slice(6,8)}T00:00:00`)
    .toLocaleDateString(undefined, { year:"numeric", month:"long", day:"numeric" });
}

const STACK = [
  {
    layer: "Data",
    color: "#7ec8ff",
    items: [{ label: "GDELT V1", note: "global event dataset" }],
  },
  {
    layer: "ML / NLP",
    color: "#a78bfa",
    items: [
      { label: "spaCy",      note: "NER",         key: "ner" },
      { label: "KMeans",     note: "clustering",  key: "clustering" },
      { label: "DistilBERT", note: "sentiment",   key: "sentiment" },
      { label: "pandas",     note: "processing" },
    ],
  },
  {
    layer: "Backend",
    color: "#93c5fd",
    items: [
      { label: "Python 3.12" },
      { label: "FastAPI" },
      { label: "uvicorn" },
      { label: "WebSocket" },
    ],
  },
  {
    layer: "AI / Media",
    color: "#e8763c",
    items: [
      { label: "Gemini API", note: "enrichment" },
      { label: "gTTS",       note: "voice" },
      { label: "ffmpeg",     note: "video" },
      { label: "Pillow",     note: "title cards" },
    ],
  },
  {
    layer: "Frontend",
    color: "#4fae8a",
    items: [
      { label: "React 19" },
      { label: "Vite" },
      { label: "d3-geo",   note: "world map" },
      { label: "recharts", note: "charts" },
    ],
  },
];

export default function Hero({ health, result }) {
  const layers = health?.ml_layers || {};

  return (
    <header className="hero">
      <div className="hero-inner">
        <p className="hero-eyebrow">GDELT Pulse — wire intelligence</p>
        <h1 className="hero-title">Daily geopolitical briefing</h1>
        <p className="hero-sub">
          Pick a date and a country. Every event reported about it that
          day gets filtered, scored, and clustered into one read.
        </p>

        {result && (
          <p className="hero-briefing">
            {result.country_name} · {formatDate(result.date)} ·{" "}
            {result.metrics.total_events.toLocaleString()} events
          </p>
        )}

        <div className="tech-stack">
          {STACK.map((group) => (
            <div key={group.layer} className="tech-group">
              <span className="tech-group-label" style={{ color: group.color }}>
                {group.layer}
              </span>
              <div className="tech-items">
                {group.items.map((item) => {
                  const inactive = item.key && !layers[item.key];
                  return (
                    <span
                      key={item.label}
                      className={`tech-pill ${inactive ? "tech-pill-off" : ""}`}
                      style={{
                        borderColor: inactive ? "var(--border)" : group.color + "55",
                        background: inactive ? "transparent" : group.color + "11",
                        color: inactive ? "var(--text-muted)" : group.color,
                      }}
                      title={inactive ? `${item.label} not installed` : item.note || item.label}
                    >
                      {item.key && (
                        <span className="tech-dot" style={{
                          background: inactive ? "var(--text-muted)" : group.color
                        }} />
                      )}
                      <span className="tech-label">{item.label}</span>
                      {item.note && (
                        <span className="tech-note" style={{ color: inactive ? "var(--text-muted)" : group.color + "aa" }}>
                          {item.note}
                        </span>
                      )}
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </header>
  );
}
