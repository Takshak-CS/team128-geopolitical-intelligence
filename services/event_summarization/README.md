# GDELT Pulse — Daily Geopolitical Intelligence Platform

Pick a date and a country. GDELT Pulse pulls that day's global news-event
data, filters it down to the country you picked, runs it through an ML
pipeline, and turns it into a readable intelligence briefing — a world map
of who that country interacted with, a network graph of the actors
involved, event cards with real article context, a domestic-vs-international
split, historical relationship context going back to 1990, and a full-screen
slide briefing.

It's built on top of the [GDELT Project](https://www.gdeltproject.org/)'s
daily global event export — a dataset of world news events coded by actor,
event type, and tone.

## What it actually does, step by step

1. **You pick a date + country.** The backend downloads (or reuses a cached
   copy of) that day's GDELT event export and filters it to events
   involving your country.
2. **ML pipeline runs on the filtered events:**
   - **spaCy NER** extracts real person/organization names out of noisy
     GDELT actor strings where possible.
   - **KMeans clustering** groups events into thematic clusters.
   - Generic GDELT role labels ("Police", "King", "Government") and
     country demonyms/nicknames ("Finn", "Britain", "London") get resolved
     into readable, attributable text — e.g. "Bahrain's police" instead of
     a bare "Police" node.
3. **Domestic vs. international split.** Events where both sides are the
   same country are separated from cross-border events — each gets its own
   view, not mixed together.
4. **Historical context (GGE).** For any country pair, a 1990–2024
   bilateral alignment score (Fan, 2025 — Global Geopolitical Events
   Database) shows whether the relationship is trending better or worse
   than the raw daily data alone would suggest.
5. **Article verification.** For any event, GDELT Pulse can fetch the
   actual source article and ask Gemini to confirm whether GDELT's own
   coding matches what really happened — flagging cases where GDELT
   miscategorized a routine story (e.g. sports coverage) as conflict, or
   where a domestic-coded event is actually international.
6. **Briefing mode.** A 5-slide full-screen presentation summarizing the
   day, with its own Domestic/International toggle.

## Tech stack

| Layer | Tools |
|---|---|
| Data | GDELT V1 global event dataset |
| ML / NLP | spaCy (NER), scikit-learn (KMeans clustering), pandas |
| Backend | Python 3.12, FastAPI, uvicorn, WebSocket (live pipeline progress) |
| AI / Media | Gemini API (article enrichment + misclassification detection), gTTS (voice), ffmpeg (video), Pillow (title cards) |
| Frontend | React 19, Vite, d3-geo (world map), d3-force (network graph), recharts (charts) |

## Running it

You need two terminals open at the same time — one for the backend, one
for the frontend.

**Terminal 1 — Backend:**
```powershell
cd C:\Users\mshre\Desktop\GDELT
.venv\Scripts\Activate.ps1
$env:GEMINI_API_KEY="your-key-here"
uvicorn src.api:app --reload --port 8000
```
Wait until it prints `Application startup complete`.

**Terminal 2 — Frontend:**
```powershell
cd C:\Users\mshre\Desktop\GDELT\frontend
npm run dev
```

Then open `http://localhost:5173` in your browser. You can check
`http://localhost:8000/health` to confirm the ML layers and GGE
historical-context database loaded correctly.

The Gemini key is only required for the article-verification features —
the rest of the app (map, network graph, GGE context, charts) works fine
without it.

### First-time setup (if dependencies aren't installed yet)

```powershell
# Backend
cd C:\Users\mshre\Desktop\GDELT
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

## Known limitations

- GDELT's own event coding is noisy: an article's country tag reflects
  where it was *published*, not necessarily who's actually involved. A
  Canadian outlet covering a US–Iran story can get coded under Canada.
  The AI article-verification feature exists specifically to catch and
  flag this class of mismatch — it isn't run automatically on every event
  (Gemini's free tier has a daily quota), so treat it as a spot-check tool
  that runs automatically on the events most likely to need it.
- Because the Domestic/International split relies on GDELT's own country
  codes (which are what's being verified), an occasional event will sit in
  the wrong tab until you click into it — at which point verification
  explains the actual scope.
- DistilBERT sentiment cross-validation is present in code but disabled by
  default (the model is large and not required for the core pipeline).
- The events table is capped at 300 rows per query for performance.
