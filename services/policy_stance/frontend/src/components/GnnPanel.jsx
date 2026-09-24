import SectionCard from './SectionCard';

export default function GnnPanel({ gnn, onTrain, loading, sessionId }) {
  return (
    <SectionCard
      title="Graph Attention Network"
      kicker="Embedding Layer"
      actions={
        <button
          className="rounded-full border border-mint/40 bg-mint/10 px-4 py-2 text-sm font-semibold text-mint disabled:opacity-40"
          disabled={!sessionId || loading}
          onClick={onTrain}
        >
          {loading ? 'Training...' : 'Train GAT'}
        </button>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-steel">Predicted Alignments</p>
          <div className="mt-3 space-y-2 max-h-56 overflow-auto pr-1 text-sm">
            {(gnn?.predicted_alignments || []).slice(0, 10).map((edge) => (
              <div key={`${edge.source}-${edge.target}`} className="flex items-center justify-between gap-3">
                <span>{edge.source} vs {edge.target}</span>
                <span className="text-mint">{edge.score}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-steel">Training Loss</p>
          <div className="mt-4 flex h-56 items-end gap-1 overflow-hidden">
            {(gnn?.loss_curve || []).slice(-40).map((value, index, arr) => (
              <div
                key={`${value}-${index}`}
                className="flex-1 rounded-t bg-ember/80"
                style={{ height: `${Math.max(8, (1 - value / Math.max(...arr, 1)) * 100)}%` }}
              />
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
