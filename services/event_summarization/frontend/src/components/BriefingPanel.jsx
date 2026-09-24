import { useState } from "react";
import BriefingMode from "./BriefingMode.jsx";

export default function BriefingPanel({ result, internationalRows, domesticRows, scope }) {
  const [showMode, setShowMode] = useState(false);

  if (!result) return null;

  return (
    <>
      {showMode && (
        <BriefingMode
          result={result}
          internationalRows={internationalRows || []}
          domesticRows={domesticRows || []}
          initialScope={scope}
          onClose={() => setShowMode(false)}
        />
      )}

      <section>
        <p className="section-label">07 · Intelligence briefing</p>
        <div className="briefing-simple">
          <div className="briefing-simple-left">
            <div className="briefing-simple-title">Briefing Mode</div>
            <div className="briefing-simple-desc">
              Full-screen presentation across 5 slides — overview, key numbers,
              top events, partner countries, and outlook. Toggle International /
              Domestic inside. Use arrow keys or click to advance. Press Esc to exit.
            </div>
          </div>
          <button
            className="run-button"
            onClick={() => setShowMode(true)}
            style={{ flexShrink: 0, fontSize: 14, padding: "12px 24px" }}
          >
            ▶ Launch briefing
          </button>
        </div>
      </section>
    </>
  );
}
