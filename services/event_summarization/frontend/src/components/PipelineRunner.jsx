import { useState, useRef, useCallback } from "react";
import { API_BASE } from "../api";

const STAGES = [
  { key: "fetch",     label: "Fetch",     desc: "Download today's global events data" },
  { key: "filter",    label: "Filter",    desc: "Match events to the selected country" },
  { key: "ner",       label: "Names",     desc: "Extract real actor names from raw text" },
  { key: "sentiment", label: "Sentiment", desc: "AI cross-check on conflict scores" },
  { key: "cluster",   label: "Cluster",   desc: "Group events into activity themes" },
  { key: "summarize", label: "Summarise", desc: "Build the intelligence narrative" },
];

export default function PipelineRunner({ date, countryCode, onResult, disabled }) {
  const [running, setRunning]     = useState(false);
  const [stages, setStages]       = useState({});
  const [pct, setPct]             = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [error, setError]         = useState("");
  const wsRef = useRef(null);

  const run = useCallback(() => {
    if (!date || !countryCode || running) return;
    setRunning(true);
    setStages({});
    setPct(0);
    setStatusMsg("Connecting…");
    setError("");

    const ws = new WebSocket(API_BASE.replace(/^http/, "ws") + "/ws/pipeline");
    wsRef.current = ws;

    ws.onopen = () => ws.send(JSON.stringify({ date, country_code: countryCode }));

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      setPct(msg.pct);
      setStatusMsg(msg.message);
      if (msg.stage !== "done" && msg.stage !== "error")
        setStages((prev) => ({ ...prev, [msg.stage]: msg.status }));
      if (msg.status === "error") { setError(msg.message); setRunning(false); ws.close(); }
      if (msg.stage === "done" && msg.status === "done") {
        setRunning(false); ws.close();
        if (msg.payload) onResult(msg.payload);
      }
    };

    ws.onerror = () => { setError("Could not connect to the backend — is it running?"); setRunning(false); };
    ws.onclose = () => { if (running) setRunning(false); };
  }, [date, countryCode, running, onResult]);

  const stageStatus = (key) => stages[key] || "idle";

  return (
    <div className="pipeline-runner">
      <button
        className="run-button"
        onClick={run}
        disabled={disabled || running || !date || !countryCode}
      >
        {running ? "Analysing…" : "Run analysis"}
      </button>

      {(running || Object.keys(stages).length > 0) && (
        <div className="pipeline-track">
          <div className="pipeline-progress-bar">
            <div className="pipeline-progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="pipeline-stages">
            {STAGES.map((s) => {
              const st = stageStatus(s.key);
              return (
                <div key={s.key} className={`pipeline-stage ps-${st}`} title={s.desc}>
                  <span className="ps-icon">
                    {st === "done" ? "✓" : st === "running" ? "◉" : st === "error" ? "✕" : "○"}
                  </span>
                  <div className="ps-text">
                    <span className="ps-label">{s.label}</span>
                    <span className="ps-desc">{s.desc}</span>
                  </div>
                </div>
              );
            })}
          </div>
          {statusMsg && !error && <p className="pipeline-status">{statusMsg}</p>}
          {error && <p className="pipeline-status pipeline-error">{error}</p>}
        </div>
      )}
    </div>
  );
}
