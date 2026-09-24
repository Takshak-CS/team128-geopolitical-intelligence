import Panel from './Panel';

export default function CountrySidebar({ profile }) {
  if (!profile) {
    return (
      <Panel title="Country Panel" subtitle="Select a node in the graph.">
        <p className="muted">Country-level details appear here once a node is selected.</p>
      </Panel>
    );
  }

  return (
    <Panel title={profile.name} subtitle={`GW code ${profile.gw_code}`}>
      <div className="info-grid compact">
        <div><span>Conflicts</span><strong>{profile.total_conflicts}</strong></div>
        <div><span>Deaths</span><strong>{Math.round(profile.total_deaths)}</strong></div>
        <div><span>Degree</span><strong>{profile.centrality.degree.toFixed(3)}</strong></div>
        <div><span>PageRank</span><strong>{profile.centrality.pagerank.toFixed(3)}</strong></div>
      </div>
      <div className="stack-list">
        <h3>Top Partners</h3>
        {profile.top_partners.slice(0, 5).map((partner) => (
          <div key={partner.country} className="list-row">
            <span>{partner.country}</span>
            <small>{partner.conflict_count} conflicts</small>
          </div>
        ))}
      </div>
      <div className="stack-list">
        <h3>UN Voting</h3>
        {Object.entries(profile.un_votes.counts || {}).map(([vote, count]) => (
          <div key={vote} className="list-row">
            <span>{vote}</span>
            <small>{count}</small>
          </div>
        ))}
      </div>
      <div className="stack-list">
        <h3>Embedding</h3>
        <small>{profile.embedding_3d.join(', ')}</small>
      </div>
    </Panel>
  );
}
