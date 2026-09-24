import SectionCard from './SectionCard';

export default function InsightPanel({ insights }) {
  return (
    <SectionCard title="Strategic Insights" kicker="Derived Signals">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-steel">Top Allies</p>
          <div className="mt-3 space-y-2">
            {(insights?.allies || []).slice(0, 6).map((ally) => (
              <div key={ally.country} className="flex items-center justify-between text-sm">
                <span>{ally.country}</span>
                <span className="text-mint">{ally.score}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-steel">Opponents</p>
          <div className="mt-3 space-y-2">
            {(insights?.opponents || []).slice(-6).map((opponent) => (
              <div key={opponent.country} className="flex items-center justify-between text-sm">
                <span>{opponent.country}</span>
                <span className="text-amber-300">{opponent.score}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/10 p-4">
          <p className="text-xs uppercase tracking-[0.25em] text-steel">Policy Shift Anomalies</p>
          <div className="mt-3 space-y-2">
            {(insights?.anomalies || []).slice(0, 6).map((anomaly, index) => (
              <div key={`${anomaly.country}-${index}`} className="text-sm">
                <p>{anomaly.country}</p>
                <p className="text-xs text-steel">{anomaly.year} | shift score {anomaly.shift_score}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
