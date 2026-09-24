import { arc, lineRadial, scaleOrdinal } from 'd3';
import { schemeTableau10 } from 'd3-scale-chromatic';

function shortName(name) {
  return (name || '')
    .replace(/^Government of /i, '')
    .replace(/\s*\(.*?\)\s*/g, '')
    .trim()
    .slice(0, 14);
}

export default function ChordDiagram({ links = [] }) {
  const size = 360;
  const radius = 140;
  const countries = [...new Set(links.flatMap((link) => [link.source, link.target]))].slice(0, 18);
  const color = scaleOrdinal(schemeTableau10).domain(countries);
  const angleStep = countries.length ? (Math.PI * 2) / countries.length : 0;
  const positions = Object.fromEntries(
    countries.map((country, index) => {
      const angle = index * angleStep - Math.PI / 2;
      return [country, { angle, x: size / 2 + Math.cos(angle) * radius, y: size / 2 + Math.sin(angle) * radius }];
    })
  );
  const ring = arc().innerRadius(radius - 10).outerRadius(radius + 10);
  const chords = links.slice(0, 30);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="chord-svg">
      <g transform={`translate(${size / 2}, ${size / 2})`}>
        {countries.map((country) => {
          const { angle } = positions[country];
          return <path key={country} d={ring({ startAngle: angle - 0.11, endAngle: angle + 0.11 }) || ''} fill={color(country)} opacity="0.9" />;
        })}
      </g>
      {chords.map((link, index) => {
        const source = positions[link.source];
        const target = positions[link.target];
        if (!source || !target) return null;
        const path = lineRadial().angle((d) => d.angle).radius((d) => d.radius)([
          { angle: source.angle, radius },
          { angle: (source.angle + target.angle) / 2, radius: 35 },
          { angle: target.angle, radius },
        ]);
        return <path key={`${link.source}-${link.target}-${index}`} d={path || ''} transform={`translate(${size / 2}, ${size / 2})`} fill="none" stroke={color(link.source)} strokeOpacity="0.45" strokeWidth={Math.max(1, link.value)} />;
      })}
      {countries.map((country) => {
        const point = positions[country];
        return (
          <text key={country} x={point.x} y={point.y} textAnchor="middle" className="chord-label">
            {shortName(country)}
          </text>
        );
      })}
    </svg>
  );
}
