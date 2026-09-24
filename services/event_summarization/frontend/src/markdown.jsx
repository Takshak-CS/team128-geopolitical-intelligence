function renderInline(text, keyPrefix) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return parts.map((chunk, i) =>
    i % 2 === 1 ? (
      <strong key={`${keyPrefix}-${i}`}>{chunk}</strong>
    ) : (
      <span key={`${keyPrefix}-${i}`}>{chunk}</span>
    )
  );
}

/**
 * Renders the narrow markdown subset produced by preprocess.py's summarize():
 * "### heading", "**bold**", "---" rules, blank-line-separated paragraphs.
 */
export function renderMarkdownLite(markdown) {
  const blocks = markdown.split(/\n\n+/);

  return blocks.map((block, bi) => {
    const trimmed = block.trim();

    if (trimmed === "---") {
      return <hr key={bi} className="script-rule" />;
    }

    if (trimmed.startsWith("### ")) {
      return (
        <h3 key={bi} className="script-heading">
          {renderInline(trimmed.slice(4), `h-${bi}`)}
        </h3>
      );
    }

    const lines = trimmed.split("\n").filter(Boolean);
    return (
      <p key={bi} className="script-paragraph">
        {lines.map((line, li) => (
          <span key={li}>
            {renderInline(line, `p-${bi}-${li}`)}
            {li < lines.length - 1 && <br />}
          </span>
        ))}
      </p>
    );
  });
}
