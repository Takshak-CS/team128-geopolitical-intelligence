export default function ViewToggle({ mode, onChange }) {
  return (
    <div className="view-toggle" role="radiogroup" aria-label="Detail level">
      <button
        type="button"
        role="radio"
        aria-checked={mode === "simple"}
        className={`view-toggle-btn ${mode === "simple" ? "active" : ""}`}
        onClick={() => onChange("simple")}
      >
        Story view
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={mode === "technical"}
        className={`view-toggle-btn ${mode === "technical" ? "active" : ""}`}
        onClick={() => onChange("technical")}
      >
        Analyst view
      </button>
    </div>
  );
}
