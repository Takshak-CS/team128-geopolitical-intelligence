const LABELS = {
  SQLDATE: "Date",
  Actor1Name: "Actor 1",
  Actor1CountryCode: "A1",
  Actor2Name: "Actor 2",
  Actor2CountryCode: "A2",
  EventType: "Event type",
  GoldsteinScale: "Goldstein",
  Tone: "Tone",
  CountryRole: "Role",
  SentimentLabel: "Sentiment",
  SentimentScore: "Confidence",
  SentimentAgreement: "Agreement",
  EventCluster: "Cluster",
};

export default function EventsTable({ rows, shown, total }) {
  if (!rows || rows.length === 0) return null;
  const columns = Object.keys(rows[0]);

  return (
    <section>
      <p className="section-label">05 · Enriched dataset</p>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{LABELS[c] || c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>
                    {row[c] === null || row[c] === undefined ? "—" : String(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="table-footnote">
        Showing {shown} of {total.toLocaleString()} matched events.
      </p>
    </section>
  );
}
