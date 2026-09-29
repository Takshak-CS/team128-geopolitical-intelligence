"""
enricher.py — Article-based event enrichment
=============================================
When GDELT can't resolve an actor name, this module:
  1. Fetches the source article URL
  2. Extracts the headline and main text
  3. Sends it to Gemini to identify the real actors and summarise what happened
  4. Returns enriched context for display on the event card

Requirements:
    pip install beautifulsoup4
    GEMINI_API_KEY set in environment (same key used by narration.py)

Designed to be called per-event on demand (user clicks "Scan article"),
not in bulk — keeps quota usage minimal.
"""

import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

ENRICH_PROMPT = """You are a geopolitical analyst checking whether a GDELT automated event record matches its source article.

GDELT coded this event as:
- Actor 1: {actor1}
- Actor 2: {actor2}
- Event type: {event_type}
- Goldstein score: {score} (range -10 conflictual to +10 cooperative)
- Country this event is filed under: {country}

Article content:
{article_text}

Your job:
1. Read the article carefully.
2. Decide whether GDELT's coding accurately reflects what the article is about.
3. If the article is about something different (e.g., GDELT coded a sports match as a Fight, or an accident as a military confrontation), flag this as a misclassification.
4. Identify EVERY country that is actually a real participant in the events the article describes — not just {country}. This matters because GDELT sometimes files an event as "domestic" to {country} when a foreign country was actually involved (e.g. coding both sides of a bilateral meeting under the host country's code, losing the visiting country entirely). This includes diaspora/expatriate-community stories — if a government official from Country A is actively promoting investment, engaging with, or courting that country's citizens/diaspora living in {country}, Country A counts as a real active participant, not just a mentioned nationality. A state or regional government official (e.g. "Andhra Pradesh Minister") represents their national government (India) for this purpose.

Hard rules for "gdelt_match" — apply these strictly, do not give GDELT the benefit of the doubt:
- A two-sided event needs BOTH "{actor1}" AND "{actor2}" (or an obvious synonym/demonym of each) to be genuine, real, active participants in what the article actually describes. One side matching is NOT sufficient — if either side is absent or is not a real participant, set gdelt_match to false, even if the present side's story is plausible on its own and even if the event category (Consultation, Cooperation, etc.) sounds generically right.
- Only set gdelt_match to true if you can point to both named parties actually being described as involved in the article's real content.

Return a JSON object with exactly these fields:
{{
  "what_happened": "1-2 sentence plain English summary of what the article is actually about",
  "real_actor1": "actual identity of Actor 1 from the article, or keep '{actor1}' if correct",
  "real_actor2": "actual identity of Actor 2 from the article, or keep '{actor2}' if correct",
  "location": "specific location from the article, or null",
  "key_detail": "one important detail that adds context",
  "gdelt_match": true or false,
  "mismatch_reason": "if gdelt_match is false, explain in one sentence why the coding is wrong. If gdelt_match is true, set to null.",
  "countries_involved": ["list every country that is a real, active participant in the article's actual events — include {country} if it genuinely is one"],
  "is_actually_international": true or false — true if a country OTHER than {country} is a real active participant (not just mentioned in passing)
}}

Return only valid JSON, no other text."""


def _fetch_article(url: str, timeout: int = 8) -> dict:
    """
    Fetches article content from a URL and extracts headline + body text.
    Uses a browser-like User-Agent to avoid basic bot blocks. Retries once
    on transient failures (timeout / connection reset) since those often
    succeed on a second attempt — does NOT retry 403/404, which won't
    change no matter how many times you ask.
    Returns dict with 'headline', 'text', 'domain'.
    """
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    resp = None
    last_err = None
    for attempt in range(2):  # 1 initial try + 1 retry, transient errors only
        try:
            resp = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
            resp.raise_for_status()
            last_err = None
            break
        except Exception as e:
            last_err = e
            err = str(e)
            is_transient = "timeout" in err.lower() or "timed out" in err.lower() or "Connection" in err
            if attempt == 0 and is_transient:
                time.sleep(1)
                continue
            break

    if last_err is not None:
        err = str(last_err)
        if "404" in err:
            return {"error": "Article no longer available — this URL has expired or been removed"}
        if "403" in err or "401" in err:
            return {"error": "Article is paywalled or access-restricted"}
        if "timeout" in err.lower() or "timed out" in err.lower():
            return {"error": "Article fetch timed out — site may be slow or blocking requests"}
        return {"error": f"Could not fetch article: {type(last_err).__name__}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove noise elements
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", "button", "iframe"]):
        tag.decompose()

    # Try to get the headline — try multiple selectors in priority order
    headline = ""
    selectors_tried = [
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
        ('meta[property="twitter:title"]', "content"),
        ("h1", None),
        ('meta[name="title"]', "content"),
        ("title", None),
    ]
    for selector, attr in selectors_tried:
        el = soup.select_one(selector)
        if not el:
            continue
        text = (el.get(attr) if attr else el.get_text()).strip()
        # Skip if it looks like just the site name (too short, no spaces, or just domain-like)
        if text and len(text) > 20 and " " in text:
            headline = text
            break

    # Clean up headline — remove site name suffixes like " | BBC News" or " - The Guardian"
    if headline:
        for sep in [" | ", " - ", " – ", " — ", " · "]:
            if sep in headline:
                parts = headline.split(sep)
                # Keep the longer part (usually the actual headline)
                headline = max(parts, key=len).strip()

    # Extract main body text — prefer article/main tags, fall back to all <p>
    body_tags = (
        soup.select("article p") or
        soup.select("main p") or
        soup.select('[class*="article"] p') or
        soup.select('[class*="content"] p') or
        soup.find_all("p")
    )
    paragraphs = [p.get_text().strip() for p in body_tags if len(p.get_text().strip()) > 60]
    body = " ".join(paragraphs[:6])  # First 6 substantive paragraphs

    # Trim to ~1200 chars so we don't blow the Gemini context budget
    if len(body) > 1200:
        body = body[:1200] + "…"

    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
    except Exception:
        domain = ""

    # Many sites render content client-side and a plain HTTP request just
    # gets back a static shell — "JavaScript is disabled", a cookie-consent
    # wall, or a bot-check page. These pass the naive length/space check
    # above and would otherwise get confidently displayed as if they were
    # the real article headline. Catch that here instead.
    PLACEHOLDER_MARKERS = [
        "javascript is disabled", "javascript is required", "please enable javascript",
        "enable javascript", "enable cookies", "checking your browser",
        "just a moment", "are you a human", "verify you are human",
        "access denied", "page not found", "404 not found", "attention required",
    ]
    combined_lower = f"{headline} {body}".lower().strip()
    looks_like_placeholder = (
        any(marker in combined_lower for marker in PLACEHOLDER_MARKERS)
        and len(body) < 200  # a real article mentioning "cookies" in passing still has real body text
    )
    if looks_like_placeholder:
        return {"error": "This site renders its content with JavaScript, which a simple fetch can't execute — no real article text was retrievable"}

    if not headline and not body:
        return {"error": "Article content could not be extracted (may be paywalled or JavaScript-rendered)"}

    return {"headline": headline, "text": body, "domain": domain}


# ── Gemini model selection ──────────────────────────────────────────────
# Google retires model names (gemini-2.0-flash is gone), so the model is
# no longer hardcoded: GEMINI_MODEL env override, else discovered once via
# client.models.list(), else a fixed fallback list.
_FALLBACK_MODELS = [
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash", "gemini-3.1-flash-lite",
]
_EXCLUDED_MODEL_WORDS = ("lite", "image", "live", "tts", "audio", "embedding", "thinking", "preview")
_FLASH_RE = re.compile(r"^gemini-(\d+)\.(\d+)-flash")

_model_name = None           # cached chosen model (read by /health)
_discovered_models = None    # cached models.list() result (list of names), [] if it failed
_fallback_index = 0          # next _FALLBACK_MODELS entry to use when discovery finds nothing
_retired_models = set()      # models that returned not-found this process


def get_cached_model_name():
    """The model currently in use, or None if none chosen yet. No network."""
    return _model_name


def _pick_flash_model(names: list):
    """Highest gemini-<major>.<minor>-flash, skipping lite/image/live/etc.
    variants unless nothing else exists."""
    candidates = []
    for n in names:
        m = _FLASH_RE.match(n)
        if m:
            candidates.append(((int(m.group(1)), int(m.group(2))), n))
    if not candidates:
        return None
    clean = [c for c in candidates if not any(w in c[1] for w in _EXCLUDED_MODEL_WORDS)]
    pool = clean or candidates
    # Highest version; among equals, prefer the shortest (base) name.
    return max(pool, key=lambda c: (c[0], -len(c[1])))[1]


def _discover_models(client) -> list:
    """Names of models supporting generateContent ("models/" prefix
    stripped). Cached at module level; [] if listing fails."""
    global _discovered_models
    if _discovered_models is None:
        try:
            names = []
            for m in client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions:
                    names.append((m.name or "").replace("models/", "", 1))
            _discovered_models = names
        except Exception as e:
            print(f"[enricher] model discovery failed: {type(e).__name__}")
            _discovered_models = []
    return _discovered_models


def get_model_name(client) -> str:
    global _model_name, _fallback_index
    if _model_name:
        return _model_name
    name = os.environ.get("GEMINI_MODEL", "").strip()
    if name in _retired_models:
        name = ""  # the override itself was not found — fall through once
    if not name:
        available = [n for n in _discover_models(client) if n not in _retired_models]
        name = _pick_flash_model(available)
    if not name:
        remaining = [m for m in _FALLBACK_MODELS[_fallback_index:] if m not in _retired_models]
        name = remaining[0] if remaining else _FALLBACK_MODELS[-1]
        _fallback_index = _FALLBACK_MODELS.index(name) + 1
    _model_name = name
    print("[enricher] using Gemini model:", name)
    return name


def _is_model_unavailable(err: str) -> bool:
    e = err.lower()
    return ("404" in e or "not_found" in e or "not found" in e
            or "no longer available" in e or "deprecated" in e)


def _gen_config(with_thinking: bool) -> dict:
    # 2000 tokens: newer models can spend part of the output budget on
    # thinking, which truncated the JSON at the old 700 limit.
    config = {
        "max_output_tokens": 2000,
        "temperature": 0.2,
        "response_mime_type": "application/json",
    }
    if with_thinking:
        config["thinking_config"] = {"thinking_budget": 0}
    return config


def _call_gemini(prompt: str) -> str:
    """Calls Gemini with a prompt, returns text response."""
    global _model_name
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("pip install google-genai to enable article enrichment")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    rate_retried = False
    model_retried = False
    thinking = True  # dropped once if a model rejects thinking_config
    while True:
        model = get_model_name(client)
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=_gen_config(thinking),
            )
            return (response.text or "").strip()
        except Exception as e:
            err = str(e)
            # Retry once on rate limit
            if "429" in err and not rate_retried:
                rate_retried = True
                time.sleep(35)
                continue
            # Some models don't accept a thinking budget — retry once without it.
            if thinking and "thinking" in err.lower() and "400" in err:
                thinking = False
                continue
            # Retired/unknown model: forget it, pick another once.
            if _is_model_unavailable(err) and not model_retried:
                model_retried = True
                print(f"[enricher] model {model} unavailable, choosing another")
                _retired_models.add(model)
                _model_name = None
                continue
            raise RuntimeError(f"Gemini error: {e}")


def enrich_event(
    url: str,
    actor1: str,
    actor2: str,
    event_type: str,
    country: str,
    score: float,
) -> dict:
    """
    Main entry point. Returns an enrichment dict:
      {
        "real_actor1": str,
        "real_actor2": str,
        "what_happened": str,
        "location": str | None,
        "key_detail": str,
        "source": "headline or domain used",
        "gdelt_match": bool,
        "mismatch_reason": str | None,
        "countries_involved": list[str],
        "is_actually_international": bool,
        "enriched": True
      }
    Or on failure:
      { "error": str, "enriched": False }
    """
    if not url or not url.startswith("http"):
        return {"enriched": False, "error": "No valid source URL for this event"}

    # Step 1 — fetch the article
    article = _fetch_article(url)
    if "error" in article:
        return {"enriched": False, "error": article["error"]}

    article_text = f"Headline: {article.get('headline', '')}\n\n{article.get('text', '')}"

    # Step 2 — call Gemini
    try:
        prompt = ENRICH_PROMPT.format(
            actor1=actor1,
            actor2=actor2,
            event_type=event_type,
            country=country,
            score=f"{score:+.1f}",
            article_text=article_text,
        )
        raw = _call_gemini(prompt)

        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

        import json
        data = json.loads(raw)

        gdelt_match = data.get("gdelt_match", True)
        countries_involved = data.get("countries_involved") or []
        is_actually_international = bool(data.get("is_actually_international", False))
        return {
            "enriched": True,
            "real_actor1":   data.get("real_actor1", actor1),
            "real_actor2":   data.get("real_actor2", actor2),
            "what_happened": data.get("what_happened", ""),
            "location":      data.get("location"),
            "key_detail":    data.get("key_detail", ""),
            "source":        article.get("headline") or article.get("domain", ""),
            "gdelt_match":   gdelt_match,
            "mismatch_reason": data.get("mismatch_reason") if not gdelt_match else None,
            "countries_involved": countries_involved,
            "is_actually_international": is_actually_international,
        }

    except Exception as e:
        # Gemini's response failed to arrive or failed to parse as JSON —
        # NEVER silently present this as a verified, trustworthy result.
        # The old fallback here returned "enriched: True" with no
        # gdelt_match field at all, which the frontend read as "nothing
        # flagged" and displayed as a plain, confident "AI VERIFIED" —
        # exactly backwards, since this is the one case where nothing was
        # actually checked. Treat it the same as a fetch failure instead,
        # so the UI correctly shows "unverified" rather than false
        # confidence.
        print(f"[enrich_event] Gemini call/parse failed: {e}")
        # Short user-facing reason. "rate" is matched as a whole word since
        # Gemini errors often mention "generateContent".
        msg = str(e).lower()
        if "429" in msg or "quota" in msg or re.search(r"\brate\b|\brate[-_ ]?limit", msg):
            reason = "AI verification is rate-limited right now"
        elif "404" in msg or "not found" in msg or "deprecated" in msg or "model" in msg:
            reason = "AI model unavailable"
        elif "json" in msg or "expecting" in msg:
            reason = "AI returned an incomplete response"
        else:
            reason = "AI verification could not complete"
        # "detail" is for debugging only (raw text, capped, key redacted);
        # the frontend shows just "error".
        detail = str(e)
        key = os.environ.get("GEMINI_API_KEY")
        if key:
            detail = detail.replace(key, "***")
        detail = re.sub(r"(key=)[^&\s'\"]+", r"\1***", detail)
        return {
            "enriched": False,
            "error": reason,
            "detail": detail[:200],
        }