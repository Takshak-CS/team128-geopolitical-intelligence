"""
article_context.py — find where an actor is mentioned in a source article
=========================================================================
Backs GET /article-context and GET /article-relevance (analyze_relevance).
Unlike enricher._fetch_article (which trims the body to ~1200 chars for
the Gemini prompt), this keeps the text of ALL substantive paragraphs so
mentions deep in the article can be surfaced.

No AI calls — plain requests + BeautifulSoup + regex.
"""

import re
import time
import socket
import ipaddress
import threading
from collections import OrderedDict
from urllib.parse import urlparse, urljoin

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 8
_MAX_REDIRECTS = 5

# Same markers enricher._fetch_article uses to spot JS/bot-check shells.
_PLACEHOLDER_MARKERS = [
    "javascript is disabled", "javascript is required", "please enable javascript",
    "enable javascript", "enable cookies", "checking your browser",
    "just a moment", "are you a human", "verify you are human",
    "access denied", "page not found", "404 not found", "attention required",
]

_MIN_PARAGRAPH_CHARS = 40
_MAX_SNIPPETS = 3
_SNIPPET_CAP = 400

# ── Small in-memory cache: url -> extracted article text ──────────────
_CACHE_MAX = 200
_cache: "OrderedDict[str, str]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(url: str):
    with _cache_lock:
        text = _cache.get(url)
        if text is not None:
            _cache.move_to_end(url)
        return text


def _cache_put(url: str, text: str):
    with _cache_lock:
        _cache[url] = text
        _cache.move_to_end(url)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)  # evict oldest


# ── URL safety ─────────────────────────────────────────────────────────
def _is_safe_url(url: str) -> bool:
    """http(s) only, and the host must not resolve to a loopback/private/
    link-local/reserved address (keeps this endpoint from being used to
    probe the server's own network)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        return False
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


# ── Fetch + extract ────────────────────────────────────────────────────
def _get_with_retry(url: str):
    """One initial try + one retry on transient errors, mirroring
    enricher._fetch_article. Redirects are followed manually so every hop
    is re-checked with _is_safe_url."""
    import requests

    last_err = None
    for attempt in range(2):
        try:
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                if not _is_safe_url(current):
                    return None
                resp = requests.get(current, timeout=_TIMEOUT, headers=_HEADERS,
                                    allow_redirects=False)
                if resp.is_redirect or resp.is_permanent_redirect:
                    location = resp.headers.get("Location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                return resp
            return None  # too many redirects
        except Exception as e:
            last_err = e
            err = str(e)
            is_transient = "timeout" in err.lower() or "timed out" in err.lower() or "Connection" in err
            if attempt == 0 and is_transient:
                time.sleep(1)
                continue
            break
    if last_err is not None:
        print(f"[article_context] fetch failed: {type(last_err).__name__}")
    return None


def _extract_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header",
                     "aside", "form", "button", "iframe"]):
        tag.decompose()

    def _paras(tags):
        out = []
        for p in tags:
            t = re.sub(r"\s+", " ", p.get_text(" ")).strip()
            if len(t) >= _MIN_PARAGRAPH_CHARS:
                out.append(t)
        return out

    paragraphs = _paras(soup.select("article p")) or _paras(soup.select("main p"))
    # If the article/main container is nearly empty (some sites put only a
    # teaser inside <article>), fall back to every <p> on the page.
    if sum(len(p) for p in paragraphs) < 500:
        all_paras = _paras(soup.find_all("p"))
        if sum(len(p) for p in all_paras) > sum(len(p) for p in paragraphs):
            paragraphs = all_paras

    # Drop exact duplicates (share widgets, repeated captions) keeping order.
    seen = set()
    unique = []
    for p in paragraphs:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return "\n".join(unique)


def _get_article_text(url: str):
    """Returns the article's paragraph text, or None if it couldn't be
    fetched or was a JS/placeholder shell."""
    cached = _cache_get(url)
    if cached is not None:
        return cached

    resp = _get_with_retry(url)
    if resp is None:
        return None

    text = _extract_text(resp.text)
    lowered = text.lower()
    if not text or (len(text) < 200 and any(m in lowered for m in _PLACEHOLDER_MARKERS)):
        return None

    _cache_put(url, text)
    return text


# ── Mention search ─────────────────────────────────────────────────────
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[\"'”’)]?\s+(?=[\"'“‘(]?[A-Z0-9])")

# Aliases that aren't in ACTOR_NORMALIZE but are how articles commonly
# refer to a country.
_EXTRA_ALIASES = {
    "united kingdom": ["Britain"],
    "united states": ["America"],
}
# ACTOR_NORMALIZE keys too ambiguous to search for as free text
# ("Kingdom" would match "United Kingdom" when looking for Saudi Arabia).
_AMBIGUOUS_ALIASES = {"kingdom"}


def _aliases_for(term: str) -> list:
    """Reverse-maps ACTOR_NORMALIZE: "United Kingdom" -> ["British", ...],
    and forward-maps a demonym to its country ("Israeli" -> "Israel")."""
    try:
        from src.preprocess import ACTOR_NORMALIZE
    except Exception:
        ACTOR_NORMALIZE = {}

    t = term.strip().lower()
    aliases = []
    for alias, canonical in ACTOR_NORMALIZE.items():
        if canonical.lower() == t:
            aliases.append(alias)
        elif alias.lower() == t:
            aliases.append(canonical)
    aliases.extend(_EXTRA_ALIASES.get(t, []))

    out = []
    for a in aliases:
        a = a.strip()
        # Short all-letter forms ("Us", "Uk") would match ordinary words
        # case-insensitively — keep only dotted forms like "U.S.".
        if (not a or a.lower() == t or a.lower() in _AMBIGUOUS_ALIASES
                or (len(a) < 4 and a.replace(" ", "").isalpha())):
            continue
        if a not in out:
            out.append(a)
    return out


def _term_pattern(terms: list):
    parts = sorted({re.escape(t) for t in terms if t}, key=len, reverse=True)
    if not parts:
        return None
    # Lookarounds instead of \b so terms ending in "." (e.g. "U.S.") still match.
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def _split_sentences(text: str) -> list:
    sentences = []
    for para in text.split("\n"):
        sentences.extend(s.strip() for s in _SENTENCE_SPLIT.split(para) if s.strip())
    return sentences


def _cap_snippet(snippet: str, core: str, pattern, cap: int = _SNIPPET_CAP) -> str:
    if len(snippet) <= cap:
        return snippet
    if len(core) <= cap:
        return core
    # A single very long sentence — window it around the first match.
    m = pattern.search(core)
    center = m.start() if m else 0
    start = max(0, center - cap // 2)
    end = min(len(core), start + cap)
    start = max(0, end - cap)
    return ("…" if start > 0 else "") + core[start:end].strip() + ("…" if end < len(core) else "")


def _search(sentences: list, pattern, max_snippets: int = _MAX_SNIPPETS, cap: int = _SNIPPET_CAP):
    snippets = []
    matched = []
    last_used = -1
    for i, sentence in enumerate(sentences):
        if len(snippets) >= max_snippets:
            break
        if i <= last_used:
            continue  # already shown as context in the previous snippet
        hits = pattern.findall(sentence)
        if not hits:
            continue
        for h in hits:
            if h.lower() not in (x.lower() for x in matched):
                matched.append(h)
        lo = max(0, i - 1)
        if lo <= last_used:
            lo = last_used + 1
        hi = min(len(sentences) - 1, i + 1)
        snippet = " ".join(sentences[lo:hi + 1])
        snippets.append(_cap_snippet(snippet, sentence, pattern, cap))
        last_used = hi
    return snippets, matched


def find_mentions(url: str, term: str) -> dict:
    """
    Returns {"found", "article_ok", "snippets", "matched_terms"}.
    - snippets: up to 3, each a matching sentence with one sentence of
      context either side, capped at ~400 chars.
    - matched_terms: the exact strings that matched (may be an alias or a
      single word of the term) so the frontend can highlight them.
    """
    result = {"found": False, "article_ok": False, "snippets": [], "matched_terms": []}
    term = (term or "").strip()
    if not term or not url or not _is_safe_url(url):
        return result

    text = _get_article_text(url)
    if not text:
        return result
    result["article_ok"] = True

    sentences = _split_sentences(text)

    # Tier 1: the full term plus known aliases/demonyms.
    tiers = [[term] + _aliases_for(term)]
    # Tier 2: individual significant words of a multi-word term.
    words = [w for w in re.split(r"\s+", term) if len(re.sub(r"\W", "", w)) >= 5]
    if len(term.split()) > 1 and words:
        tiers.append(words)

    for terms in tiers:
        pattern = _term_pattern(terms)
        if pattern is None:
            continue
        snippets, matched = _search(sentences, pattern)
        if snippets:
            result.update(found=True, snippets=snippets, matched_terms=matched)
            break
    return result


# ── Relevance analysis (backs GET /article-relevance) ─────────────────
# Judges, from the full article text, how well the article supports the
# two actors GDELT attached to an event. Local only: regex + (optionally)
# the spaCy model preprocess.py already loads. No AI calls.
_RELEVANCE_MAX_CHARS = 60_000
_RELEVANCE_MAX_SNIPPETS = 2
_RELEVANCE_SNIPPET_CAP = 350
_SHORT_ALIAS_LEN = 3  # aliases this short (US, UK, UAE) match case-sensitively

_GENERIC_MARKERS = ("unnamed", "unidentified", "unspecified", "unknown", "bloc actor",
                    # fallback labels the frontend substitutes for a missing actor
                    "an actor", "another party")

# Common ways articles refer to a country that ACTOR_NORMALIZE doesn't cover.
# Plurals ("Danes", "Israelis") are handled by the matcher's optional "s".
_RELEVANCE_EXTRA = {
    "united states": ["US", "U.S.", "USA", "U.S.A."],
    "united kingdom": ["UK", "U.K.", "Briton", "Brit"],
    "uae": ["United Arab Emirates", "Emirates"],
    "united arab emirates": ["UAE", "Emirati", "Emirates"],
    "saudi arabia": ["Saudi"],
    "netherlands": ["Holland"],
    "denmark": ["Dane"],
    "sweden": ["Swede"],
    "turkey": ["Türkiye", "Turkiye"],
    "czech republic": ["Czechia"],
    "north korea": ["North Korean", "DPRK"],
    "south korea": ["South Korean"],
    "ivory coast": ["Côte d'Ivoire", "Cote d'Ivoire"],
    "myanmar": ["Burma"],
    "bosnia and herzegovina": ["Bosnia"],
    "new zealand": ["New Zealander"],
    "philippines": ["Philippine"],
}

# Abbreviations spaCy tags as GPE, folded to the name the actor rows use.
_PLACE_ABBREV = {
    "US": "United States", "U.S.": "United States", "USA": "United States",
    "U.S.A.": "United States", "UK": "United Kingdom", "U.K.": "United Kingdom",
    "UAE": "UAE",
}


def _is_generic(term: str) -> bool:
    t = (term or "").lower()
    return any(m in t for m in _GENERIC_MARKERS)


def _actor_normalize() -> dict:
    try:
        from src.preprocess import ACTOR_NORMALIZE
        return ACTOR_NORMALIZE
    except Exception:
        return {}


def _relevance_aliases(term: str) -> list:
    """All the strings that count as a mention of `term`: the term itself,
    its canonical country (if `term` is a demonym/capital), every
    ACTOR_NORMALIZE key that maps to that country, and a few extras.
    Short all-letter aliases are upper-cased ("Us" -> "US") because they
    are matched case-sensitively."""
    normalize = _actor_normalize()
    t = term.strip()
    lowered = {k.lower(): v for k, v in normalize.items()}
    canonical = lowered.get(t.lower(), t)
    cl = canonical.lower()

    candidates = [t, canonical]
    candidates += [k for k, v in normalize.items() if v.lower() == cl]
    candidates += _RELEVANCE_EXTRA.get(cl, [])

    out, seen = [], set()
    for a in candidates:
        a = a.strip()
        if not a or a.lower() in _AMBIGUOUS_ALIASES:
            continue
        if len(a) <= _SHORT_ALIAS_LEN and a.replace(" ", "").isalpha():
            a = a.upper()
        key = a if len(a) <= _SHORT_ALIAS_LEN else a.lower()
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


class _TermMatcher:
    """Whole-word matcher over a set of aliases. Aliases longer than 3
    chars match case-insensitively (with an optional plural "s"); shorter
    ones (US, UK, UAE) match case-sensitively so "us"/"uk" in ordinary
    prose don't count. Exposes search()/findall() so it can be passed to
    _search() in place of a compiled pattern."""

    def __init__(self, aliases: list):
        self.aliases = aliases
        long_ = sorted({a for a in aliases if len(a) > _SHORT_ALIAS_LEN}, key=len, reverse=True)
        short = sorted({a for a in aliases if len(a) <= _SHORT_ALIAS_LEN}, key=len, reverse=True)
        self._patterns = []
        if long_:
            self._patterns.append(re.compile(
                r"(?<!\w)(?:" + "|".join(map(re.escape, long_)) + r")s?(?!\w)", re.IGNORECASE))
        if short:
            self._patterns.append(re.compile(
                r"(?<!\w)(?:" + "|".join(map(re.escape, short)) + r")(?!\w)"))

    def finditer(self, text: str) -> list:
        matches = sorted((m for p in self._patterns for m in p.finditer(text or "")),
                         key=lambda m: (m.start(), -m.end()))
        out, last_end = [], -1
        for m in matches:  # drop overlaps between the two patterns
            if m.start() >= last_end:
                out.append(m)
                last_end = m.end()
        return out

    def findall(self, text: str) -> list:
        return [m.group(0) for m in self.finditer(text)]

    def search(self, text: str):
        found = self.finditer(text)
        return found[0] if found else None


def _clean_entity(name: str) -> str:
    n = re.sub(r"\s+", " ", name).strip()
    n = re.sub(r"^the\s+", "", n, flags=re.IGNORECASE)
    n = re.sub(r"['’]s$", "", n)
    return n.strip(" ,;:\"'“”‘’()[]")


def _normalize_place(name: str, label: str):
    """Folds a spaCy GPE/NORP/LOC entity into a country name where
    ACTOR_NORMALIZE allows ("Danish" -> "Denmark", "Americans" ->
    "United States"). NORP entities that aren't nationalities ("Muslims",
    "Republicans") are dropped — they aren't places."""
    n = _clean_entity(name)
    if len(n) < 2:
        return None
    if n in _PLACE_ABBREV:
        return _PLACE_ABBREV[n]
    lowered = {k.lower(): v for k, v in _actor_normalize().items()}
    for candidate in (n, n[:-1] if n.endswith("s") else None):
        if candidate and len(candidate) > _SHORT_ALIAS_LEN and candidate.lower() in lowered:
            return lowered[candidate.lower()]
    if label == "NORP":
        return None
    return n


def _entity_summary(text: str):
    """(named_places, main_entities) via the backend's spaCy model, or
    ([], []) if spaCy isn't available."""
    try:
        from src.preprocess import _get_nlp
        nlp = _get_nlp()
    except Exception:
        nlp = None
    if nlp is None:
        return [], []

    try:
        disable = [p for p in ("parser", "lemmatizer") if p in nlp.pipe_names]
        doc = nlp(text[:_RELEVANCE_MAX_CHARS], disable=disable)
    except Exception as e:
        print(f"[article_context] spaCy failed: {type(e).__name__}")
        return [], []

    places, people, orgs = {}, {}, {}
    for ent in doc.ents:
        if ent.label_ in ("GPE", "NORP", "LOC"):
            place = _normalize_place(ent.text, ent.label_)
            if place:
                places[place] = places.get(place, 0) + 1
        elif ent.label_ in ("PERSON", "ORG"):
            n = _clean_entity(ent.text)
            if len(n) < 2 or "\n" in n:
                continue
            bucket = people if ent.label_ == "PERSON" else orgs
            bucket[n] = bucket.get(n, 0) + 1

    # Fold surname-only mentions ("Bardot") into the full name ("Brigitte
    # Bardot") when exactly one full name ends with that surname.
    for short in [p for p in people if " " not in p]:
        owners = [p for p in people if " " in p and p.split()[-1] == short]
        if len(owners) == 1:
            people[owners[0]] += people.pop(short)

    named_places = [{"name": k, "count": v}
                    for k, v in sorted(places.items(), key=lambda kv: -kv[1])[:6]]
    entities = [(k, "PERSON", v) for k, v in people.items()] + [(k, "ORG", v) for k, v in orgs.items()]
    main_entities = [{"name": k, "label": lbl, "count": v}
                     for k, lbl, v in sorted(entities, key=lambda e: -e[2])[:4]]
    return named_places, main_entities


def _prominence(count: int, in_headline: bool) -> str:
    if in_headline or count >= 3:
        return "central"
    return "passing" if count > 0 else "absent"


# ── List-like sentences ────────────────────────────────────────────────
# A sentence naming 4+ places ("... India, Japan, Mexico and Brazil ...")
# is a roundup/list, not a description of the actors interacting.
_LIST_LIKE_MIN_PLACES = 4
_EXTRA_PLACES = (
    "Palestine", "Gaza", "West Bank", "Cyprus", "Ireland", "Luxembourg", "New Zealand",
    "Cambodia", "Laos", "Brunei", "Bhutan", "Maldives", "Hong Kong", "Macau",
    "South Africa", "Angola", "Cameroon", "Chad", "Congo", "Rwanda", "Burundi", "Tanzania",
    "Mozambique", "Namibia", "Botswana", "Madagascar", "Niger", "Burkina Faso", "Guinea",
    "Liberia", "Sierra Leone", "Eritrea", "Djibouti", "South Sudan", "Mauritania", "Gabon",
    "Benin", "Togo", "Malawi", "Lesotho", "Eswatini", "Kosovo", "Liechtenstein", "Monaco",
    "Andorra", "San Marino", "Belize", "Guyana", "Suriname", "Bahamas", "Barbados",
    "Fiji", "Papua New Guinea", "Timor-Leste", "Europe", "Africa", "Asia",
)
_place_matcher_cache = None


def _place_matcher():
    """(_TermMatcher over country names/demonyms/abbreviations, alias->canonical)."""
    global _place_matcher_cache
    if _place_matcher_cache is None:
        canon = {}
        for k, v in _actor_normalize().items():
            if k.lower() not in _AMBIGUOUS_ALIASES:
                canon[k.lower()] = v
            canon[v.lower()] = v
        for v, extras in _RELEVANCE_EXTRA.items():
            for e in extras:
                canon.setdefault(e.lower(), canon.get(v, v))
        for k, v in _PLACE_ABBREV.items():
            canon[k.lower()] = v
        for p in _EXTRA_PLACES:
            canon.setdefault(p.lower(), p)
        aliases = []
        for a in canon:
            if len(a) <= _SHORT_ALIAS_LEN and a.replace(" ", "").isalpha():
                aliases.append(a.upper())
            else:
                aliases.append(a)
        _place_matcher_cache = (_TermMatcher(aliases), canon)
    return _place_matcher_cache


def _is_list_like(sentence: str) -> bool:
    matcher, canon = _place_matcher()
    places = set()
    for hit in matcher.findall(sentence):
        h = hit.lower()
        places.add(canon.get(h) or canon.get(h[:-1]) or h)
    return len(places) >= _LIST_LIKE_MIN_PLACES


def _best_snippet(sentences: list, m1, m2) -> str:
    """The single most informative sentence: non-list-like with both terms,
    else non-list-like with either (term1 first), else list-like with either."""
    real = [m for m in (m1, m2) if m is not None]
    if not real:
        return ""
    hits = []  # (sentence, list_like, has1, has2)
    for s in sentences:
        h1 = m1 is not None and m1.search(s) is not None
        h2 = m2 is not None and m2.search(s) is not None
        if h1 or h2:
            hits.append((s, _is_list_like(s), h1, h2))
    order = []
    if m1 is not None and m2 is not None:
        order.append(lambda x: not x[1] and x[2] and x[3])
    order += [lambda x: not x[1] and x[2], lambda x: not x[1] and x[3],
              lambda x: x[2], lambda x: x[3]]
    for rule in order:
        for s, _ll, h1, h2 in hits:
            if rule((s, _ll, h1, h2)):
                return _cap_snippet(s, s, m1 if h1 else m2, _RELEVANCE_SNIPPET_CAP)
    return ""


def _link(terms: list, same: bool, sentences: list, matchers: list, main_entities: list):
    """Returns (link, verdict_text). link is together | listed | one_sided |
    none | unavailable (generic labels that can't be matched by name)."""
    actor_names = {t["term"].lower() for t in terms}
    focus = next((e for e in main_entities if e["name"].lower() not in actor_names), None)
    about = f" The article is mainly about {focus['name']}." if focus else ""

    real = [(t, m) for t, m in zip(terms, matchers) if m is not None]
    generic = [t for t, m in zip(terms, matchers) if m is None]

    if not real:
        if same:
            return "unavailable", f"\"{terms[0]['term']}\" is a generic label, so the article can't be checked by name."
        return "unavailable", "Both actors are generic labels, so the article can't be checked by name."

    present = [(t, m) for t, m in real if t["count"] > 0]
    absent = [t for t, m in real if t["count"] == 0]

    if same or (generic and len(real) == 1):
        t, m = real[0]
        name = t["term"]
        if not present:
            return "none", f"{name} isn't named in this article — GDELT likely mis-tagged it.{about}"
        if generic:
            return "unavailable", (f"{name} is named, but \"{generic[0]['term']}\" is a generic "
                                   f"label that can't be checked by name.")
        if any(m.search(s) and not _is_list_like(s) for s in sentences):
            return "together", f"{name} is named in the article."
        return "listed", (f"{name} is named, but only in a list — the article doesn't describe "
                          f"it directly.{about}")

    (t1, m1), (t2, m2) = real
    if len(absent) == 2:
        return "none", (f"Neither {t1['term']} nor {t2['term']} is named in this article — "
                        f"GDELT likely mis-tagged it.{about}")
    if absent:
        return "one_sided", (f"Only {present[0][0]['term']} is named in the article; "
                             f"{absent[0]['term']} isn't mentioned.{about}")
    if any(m1.search(s) and m2.search(s) and not _is_list_like(s) for s in sentences):
        return "together", "Both are named together in the article."
    return "listed", ("Both are named, but only in a list or in separate places — the article "
                      f"doesn't describe them interacting.{about}")


def analyze_relevance(url: str, term1: str, term2: str, headline: str = None) -> dict:
    """
    Infers from the full article text how well the article supports the
    event's two actors. See api.py GET /article-relevance for the shape.
    Each term entry also carries "aliases" (the strings that counted as a
    mention) so the frontend can highlight them.
    """
    term1 = (term1 or "").strip()
    term2 = (term2 or "").strip()
    headline = (headline or "").strip()

    result = {
        "article_ok": False, "reason": None, "terms": [], "cooccur_sentences": 0,
        "named_places": [], "main_entities": [],
        "link": "unavailable", "verdict_text": "", "best_snippet": "",
    }

    def _unavailable(reason: str) -> dict:
        result["reason"] = reason
        result["verdict_text"] = "The article text couldn't be retrieved, so relevance can't be judged."
        return result

    if not url or not _is_safe_url(url):
        return _unavailable("URL is not an allowed public http(s) address")
    text = _get_article_text(url)
    if not text:
        return _unavailable("Article could not be fetched or had no readable text")
    return _analyze_text(text, term1, term2, headline, result)


def _analyze_text(text: str, term1: str, term2: str, headline: str, result: dict) -> dict:
    """The fetch-independent part of analyze_relevance (split out so it can
    be exercised on sample text without a network call)."""
    same = term1.lower() == term2.lower()
    text = text[:_RELEVANCE_MAX_CHARS]
    result["article_ok"] = True

    sentences = _split_sentences(text)
    first_paragraph = text.split("\n", 1)[0]

    matchers = []
    for term in ([term1] if same else [term1, term2]):
        generic = not term or _is_generic(term)
        matcher = None if generic else _TermMatcher(_relevance_aliases(term))
        entry = {"term": term, "count": 0, "in_headline": False, "in_first_paragraph": False,
                 "prominence": "n/a", "snippets": [], "aliases": []}
        if matcher is not None:
            entry["count"] = len(matcher.finditer(text))
            entry["in_headline"] = bool(headline) and matcher.search(headline) is not None
            entry["in_first_paragraph"] = matcher.search(first_paragraph) is not None
            entry["prominence"] = _prominence(entry["count"], entry["in_headline"])
            entry["snippets"], _ = _search(sentences, matcher,
                                           _RELEVANCE_MAX_SNIPPETS, _RELEVANCE_SNIPPET_CAP)
            entry["aliases"] = matcher.aliases
        result["terms"].append(entry)
        matchers.append(matcher)

    if len(matchers) == 2 and all(matchers):
        result["cooccur_sentences"] = sum(
            1 for s in sentences if matchers[0].search(s) and matchers[1].search(s))

    result["named_places"], result["main_entities"] = _entity_summary(text)
    result["best_snippet"] = _best_snippet(sentences, matchers[0],
                                           matchers[1] if len(matchers) == 2 else None)
    result["link"], result["verdict_text"] = _link(
        result["terms"], same, sentences, matchers, result["main_entities"])
    return result
