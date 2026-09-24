import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import SectionCard from './SectionCard';

export default function TemporalChart({ data, country }) {
  return (
    <SectionCard title="Temporal Stance Evolution" kicker="Yearly Drift Tracking">
      <ResponsiveContainer width="100%" height={360}>
        <LineChart data={data || []}>
          <CartesianGrid stroke="rgba(148, 163, 184, 0.12)" strokeDasharray="3 3" />
          <XAxis dataKey="year" stroke="#8aa5bf" />
          <YAxis stroke="#8aa5bf" />
          <Tooltip contentStyle={{ background: '#09141f', border: '1px solid rgba(255,255,255,0.12)' }} />
          <Line type="monotone" dataKey="relation_mean" name={`${country || 'Country'} relation`} stroke="#ff8c42" strokeWidth={3} dot={false} />
          <Line type="monotone" dataKey="intensity_mean" name="Intensity" stroke="#62d2a2" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </SectionCard>
  );
}
