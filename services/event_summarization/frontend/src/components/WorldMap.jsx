import { useMemo, useState } from "react";
import { feature } from "topojson-client";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import landTopo from "world-atlas/land-110m.json";
import { COUNTRY_CENTROIDS } from "../countryCentroids";
import InfoTip from "./InfoTip.jsx";

const WIDTH  = 680;
const HEIGHT = 340;
const COOP   = "#4fae8a";
const CONFLICT = "#d6604f";
const NEUTRAL  = "#6e92a3";

function toneColor(score) {
  if (score >= 1)  return COOP;
  if (score <= -1) return CONFLICT;
  return NEUTRAL;
}

function toneLabel(score) {
  if (score >= 1)  return "cooperative";
  if (score <= -1) return "conflictual";
  return "neutral";
}

function RichTooltip({ point, tableRows, selectedCountryCode }) {
  const [x, y] = point.xy;
  const boxW = 200;
  const boxX = Math.min(Math.max(x - boxW / 2, 6), WIDTH - boxW - 6);
  const boxY = y - 80 >= 6 ? y - 80 : y + 14;

  // Count event types involving this partner from the full table
  const related = (tableRows || []).filter(
    (r) =>
      r.Actor1CountryCode === point.code || r.Actor2CountryCode === point.code
  );
  const typeCounts = {};
  related.forEach((r) => {
    typeCounts[r.EventType] = (typeCounts[r.EventType] || 0) + 1;
  });
  const topType = Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0];

  return (
    <g pointerEvents="none">
      <rect x={boxX} y={boxY} width={boxW} height={topType ? 70 : 52} rx={6}
        className="map-tooltip-box" />
      <text x={boxX + 10} y={boxY + 18} className="map-tooltip-title">
        {point.name}
      </text>
      <text x={boxX + 10} y={boxY + 35} className="map-tooltip-sub">
        {point.count} events · {toneLabel(point.avg_goldstein)}
      </text>
      {topType && (
        <text x={boxX + 10} y={boxY + 52} className="map-tooltip-sub">
          mainly: {topType[0]}
        </text>
      )}
      <text x={boxX + 10} y={topType ? boxY + 66 : boxY + 50} className="map-tooltip-hint">
        click to explore →
      </text>
    </g>
  );
}

export default function WorldMap({ countryCode, countryName, partners, tableRows, onPartnerClick }) {
  const [hovered, setHovered] = useState(null);

  const { landPath, projection } = useMemo(() => {
    const geo  = feature(landTopo, landTopo.objects.land);
    const proj = geoNaturalEarth1().fitSize([WIDTH, HEIGHT], geo);
    return { landPath: geoPath(proj)(geo), projection: proj };
  }, []);

  const selectedCentroid = COUNTRY_CENTROIDS[countryCode];
  const selectedXY       = selectedCentroid ? projection(selectedCentroid) : null;

  const partnerPoints = (partners || [])
    .map((p) => {
      const centroid = COUNTRY_CENTROIDS[p.code];
      if (!centroid) return null;
      return { ...p, xy: projection(centroid) };
    })
    .filter(Boolean)
    .sort((a, b) => b.count - a.count);

  const maxCount    = Math.max(1, ...partnerPoints.map((p) => p.count));
  const hoveredPoint = partnerPoints.find((p) => p.code === hovered);

  return (
    <section>
      <p className="section-label">
        01 · Where today's signal points
        <InfoTip>
          Arcs connect {countryName || "this country"} to the countries it
          was reported alongside today. Hover any dot or row for a summary.
          Click to explore all events between the two countries.
        </InfoTip>
      </p>

      <div className="map-card">
        <div className="map-layout">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="map-svg"
            role="img"
            aria-label={`World map highlighting ${countryName}`}
          >
            <path d={landPath} className="map-land" />

            {selectedXY &&
              partnerPoints.map((p) => {
                const [x1, y1] = selectedXY;
                const [x2, y2] = p.xy;
                const dx = x2 - x1, dy = y2 - y1;
                const dist = Math.sqrt(dx * dx + dy * dy) || 1;
                const curve = Math.min(dist * 0.22, 36);
                const mx = (x1 + x2) / 2 - (dy / dist) * curve;
                const my = (y1 + y2) / 2 + (dx / dist) * curve;
                const width  = 1 + (p.count / maxCount) * 2.6;
                const dimmed = hovered && hovered !== p.code;
                return (
                  <path
                    key={p.code}
                    d={`M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`}
                    className="map-arc"
                    stroke={toneColor(p.avg_goldstein)}
                    strokeWidth={width}
                    opacity={dimmed ? 0.1 : 0.7}
                  />
                );
              })}

            {partnerPoints.map((p) => {
              const r      = 3 + (p.count / maxCount) * 4;
              const dimmed = hovered && hovered !== p.code;
              const labelBelow = p.xy[1] < 40;
              return (
                <g
                  key={p.code}
                  className="map-marker"
                  style={{ cursor: "pointer" }}
                  onMouseEnter={() => setHovered(p.code)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onPartnerClick && onPartnerClick(p)}
                  opacity={dimmed ? 0.25 : 1}
                >
                  <circle cx={p.xy[0]} cy={p.xy[1]} r={r + 8} fill="transparent" />
                  <circle
                    cx={p.xy[0]} cy={p.xy[1]} r={r}
                    fill={toneColor(p.avg_goldstein)}
                    className="map-partner-dot"
                    stroke={hovered === p.code ? "#fff" : "var(--surface)"}
                    strokeWidth={hovered === p.code ? 1.5 : 1}
                  />
                  <text
                    x={p.xy[0]}
                    y={labelBelow ? p.xy[1] + r + 12 : p.xy[1] - r - 6}
                    textAnchor="middle"
                    className="map-label"
                  >
                    {p.code}
                  </text>
                </g>
              );
            })}

            {selectedXY && (
              <>
                <circle cx={selectedXY[0]} cy={selectedXY[1]} r={10}
                  className="map-selected-glow" />
                <circle cx={selectedXY[0]} cy={selectedXY[1]} r={5}
                  className="map-selected-dot" />
                <text x={selectedXY[0]} y={selectedXY[1] - 15}
                  textAnchor="middle" className="map-label map-label-self">
                  {countryCode}
                </text>
              </>
            )}

            {hoveredPoint && (
              <RichTooltip
                point={hoveredPoint}
                tableRows={tableRows}
                selectedCountryCode={countryCode}
              />
            )}
          </svg>

          {/* Sidebar */}
          <div className="map-sidebar">
            <p className="map-sidebar-title">Top connections</p>
            {partnerPoints.length === 0 && (
              <p className="map-empty-note">No partner countries identified.</p>
            )}
            {partnerPoints.map((p) => (
              <div
                key={p.code}
                className={`map-sidebar-row ${hovered === p.code ? "active" : ""}`}
                onMouseEnter={() => setHovered(p.code)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onPartnerClick && onPartnerClick(p)}
                style={{ cursor: "pointer" }}
                title="Click to explore events with this country"
              >
                <span className="legend-dot"
                  style={{ background: toneColor(p.avg_goldstein) }} />
                <span className="map-sidebar-name">{p.name}</span>
                <span className="map-sidebar-count">{p.count}</span>
                <span className="map-sidebar-arrow">›</span>
              </div>
            ))}
          </div>
        </div>

        <div className="map-legend">
          <span><span className="legend-dot" style={{ background: COOP }} /> cooperative</span>
          <span><span className="legend-dot" style={{ background: CONFLICT }} /> conflictual</span>
          <span><span className="legend-dot" style={{ background: NEUTRAL }} /> neutral</span>
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            hover to preview · click to explore
          </span>
        </div>
      </div>
    </section>
  );
}
