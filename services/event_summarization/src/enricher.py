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
1. Read the article carefully
2. Decide whether GDELT's coding accurately reflects what the article is about
3. If the article is about something different (e.g., GDELT coded a sports match as a Fight, or an accident as a military confrontation), flag this as a misclassification
4. Identify EVERY country that is actually a real participant in the events the article describes — not just {country}. This matters because GDELT sometimes files an event as "domestic" to {country} when a foreign country was actually involved (e.g. coding both sides of a bilateral meeting under the host country's code, losing the visiting country entirely).

Return a JSON object with exactly these fields:
{{
  "what_happened": "1-2 sentence plain English summary of what the article is actually about",
  "real_actor1": "actual identity of Actor 1 from the article, or keep '{actor1}' if correct",
  "real_actor2": "actual identity of Actor 2 from the article, or keep '{actor2}' if correct",
  "location": "specific location from the article, or null",
  "key_detail": "one important detail that adds context",
  "gdelt_match": true or false — does GDELT's coding accurately reflect the article content?,
  "mismatch_reason": "if gdelt_match is false, explain in one sentence why the coding is wrong (e.g. 'This is a sports article, not a military conflict'). If gdelt_match is true, set to null.",
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


def _call_gemini(prompt: str) -> str:
    """Calls Gemini with a prompt, returns text response."""
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("pip install google-genai to enable article enrichment")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    # Retry once on rate limit
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={"max_output_tokens": 200, "temperature": 0.2},
            )
            return (response.text or "").strip()
        except Exception as e:
            if "429" in str(e) and attempt == 0:
                time.sleep(35)
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

    # Step 2 — check if we actually need enrichment
    # (if both actors are already resolved, just return the article summary)
    needs_enrichment = any(
        phrase in (actor1 + actor2).lower()
        for phrase in ["unidentified", "unnamed", "unknown", "an actor"]
    )

    # Step 3 — call Gemini
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
        # Gemini failed — fall back to showing just the article headline
        headline = article.get("headline", "")
        if headline:
            return {
                "enriched": True,
                "what_happened": headline,
                "real_actor1": actor1,
                "real_actor2": actor2,
                "location": None,
                "key_detail": "",
                "source": article.get("domain", ""),
                "fallback": True,
            }
        return {"enriched": False, "error": f"Enrichment failed: {e}"}