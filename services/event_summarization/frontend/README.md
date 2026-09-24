# GDELT Pulse — frontend

React (Vite) dashboard for the GDELT Video Intelligence API.

## Setup

Place this `frontend/` folder inside your existing GDELT project, next to
`src/` and `app.py` — it doesn't touch or depend on your Python code, it
just talks to the FastAPI backend over HTTP.

```
GDELT/
  src/            <- your existing Python backend
  app.py          <- your existing Streamlit app (untouched)
  frontend/       <- this folder
  data/
  requirements.txt
```

## Run

```
cd frontend
npm install
npm run dev
```

Open the URL it prints (usually http://localhost:5173). Make sure the
FastAPI backend is also running in another terminal:

```
uvicorn src.api:app --reload --port 8000
```

The frontend reads the backend URL from `.env` (`VITE_API_URL`), already
set to `http://localhost:8000`.

## What's here

- `src/api.js` — all calls to the backend (`/health`, `/dates`,
  `/countries`, `/analyze`, `/briefing`)
- `src/App.jsx` — page state: selected date/country, loading, results
- `src/components/` — one file per section of the dashboard:
  - `Hero` — title + ML layer status
  - `ControlPanel` — date input, cached-date chips, country select, run button
  - `MetricsGrid` — the four headline stat cards
  - `ChartsPanel` — event-type bar chart + tone/sentiment/cluster donuts
  - `TopEventsWire` — the 5 most significant events, as a wire-feed
  - `EventsTable` — full enriched table
  - `NarrationPanel` — the stats-based script, with a copy button
  - `BriefingPanel` — Phase 3: sends that script to Gemini to rewrite as a
    broadcast narration, then plays back the generated video brief
- `src/markdown.jsx` — tiny renderer for the `###` / `**bold**` markdown
  the backend's `summarize()` produces (no markdown library needed)

## Phase 3 (`BriefingPanel`) setup

This calls the backend's `/briefing` endpoint, which needs its own setup —
see `src/narration.py` in the backend for the full requirements
(a `GEMINI_API_KEY` (free, no card), ffmpeg on PATH, and `pip install google-genai gTTS
Pillow python-dotenv`). If those aren't set up yet, the button will show
a clear error explaining what's missing rather than failing silently.

## Not built yet (by design, for now)

- World map and a live, per-stage animated pipeline view — next up
- Multi-day trend view — stretch goal, not blocking the core demo
