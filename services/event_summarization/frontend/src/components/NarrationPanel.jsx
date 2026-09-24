import { useState } from "react";
import { renderMarkdownLite } from "../markdown.jsx";

export default function NarrationPanel({ script }) {
  const [copied, setCopied] = useState(false);

  if (!script) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(script);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (_) {
      /* clipboard not available — silently ignore */
    }
  };

  return (
    <section>
      <p className="section-label">06 · Narration script</p>
      <div className="script-page">
        {renderMarkdownLite(script)}

        <div className="script-actions">
          <button className="script-action" onClick={handleCopy}>
            {copied ? "Copied" : "Copy script"}
          </button>
        </div>
      </div>
    </section>
  );
}
