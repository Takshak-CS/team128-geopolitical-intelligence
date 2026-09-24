# Geopolitical Intelligence System — Policy Stance Analyser

## Start

Run:

```bash
bash start.sh
```

Backend API docs:

```text
http://localhost:8000/docs
```

Frontend:

```text
http://localhost:5173
```

## What each page shows

- **Dashboard**: backend readiness, summary metrics, dataset inventory, and a mini force-graph preview.
- **Network Graph**: yearly 3D relationship graph with dataset and intensity filters plus a country sidebar.
- **Country Comparison**: pairwise similarity, shared conflicts, shared votes, and radar/line charts.
- **Heatmaps**: backend-generated PNG heatmaps for conflict intensity, UN voting, and country similarity.
- **Temporal Analysis**: country trend lines, global deaths, new conflicts by year, and an animated yearly graph.
- **Alliance Blocs**: embedding scatter plot, bloc membership, and chord-style conflict flows.
- **Policy Stance**: stance matrix, issue activity charts, agreement network, temporal stance shifts, and UN topic deep-dive.

## Outputs

All generated outputs are written to:

```text
./outputs/
```

This includes parsed codebooks, graph exports, temporal graph JSON files, embeddings, similarity matrices, chord data, and heatmap PNGs.

## Adding a new dataset

1. Drop a CSV, ZIP, or XLSX file into the project root.
2. Optionally add its PDF codebook to the same folder.
3. Restart the backend.

The loader scans the current directory automatically and skips files it cannot parse without crashing the app.

## Notes

- The backend is written to use project-relative paths only.
- Missing datasets or missing columns are handled defensively.
- On this machine, the Python environment is 32-bit, so the graph embedding stage falls back to a classical random-walk embedding when PyTorch Geometric is unavailable.
