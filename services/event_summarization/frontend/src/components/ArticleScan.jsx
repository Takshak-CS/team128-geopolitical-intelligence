import { useState, useEffect, useRef } from "react";
import { getArticleHeadline, enrichEvent, getArticleRelevance } from "../api";

const EVENT_MEANINGS = {
  "Fight":                "active physical fighting",
  "Assault":              "an assault or attack",
  "Mass Violence":        "mass violence",
  "Coerce":               "coercive pressure",
  "Threaten":             "a threat or ultimatum",
  "Exhibit Force":        "a show of military force",
  "Reduce Relations":     "a reduction in diplomatic relations",
  "Protest":              "a protest or demonstration",
  "Disapprove":           "a public condemnation",
  "Reject":               "a rejection of a proposal",
  "Demand":               "a formal demand or decree",
  "Investigation":        "a formal investigation",
  "Verbal Cooperation":   "a diplomatic statement of cooperation",
  "Material Cooperation": "material or financial cooperation",
  "Diplomatic Cooperation": "diplomatic cooperation",
  "Consultation":         "diplomatic consultations",
  "Mediation":            "an attempt at mediation",
  "Provision of Aid":     "provision of aid or assistance",
  "Yield / Concession":   "a significant concession or agreement",
  "Engagement":           "diplomatic engagement",
};

function buildDataSummary({ actor1, actor2, score, country, numArticles, role, cluster, eventType }) {
  const tone =
    score <= -8 ? "maximum conflict severity" :
    score <= -5 ? "severe conflict" :
    score <= -1 ? "tense confrontation" :
    score >= 8  ? "strongly cooperative" :
    score >= 4  ? "significant cooperation" :
    score >= 1  ? "cooperative engagement" : "neutral exchange";

  const meaning = EVENT_MEANINGS[eventType] || "a notable interaction";

  const a1 = actor1.includes("unidentified") || actor1.includes("an actor") ? "an unidentified actor" : actor1;
  const a2 = actor2.includes("unidentified") ? "an unidentified party" : actor2;

  // Hedged, not asserted — this is GDELT's raw coding with NO article
  // verification behind it, so it must read as a claim GDELT made, not
  // as something that happened.
  let eventSentence = "";
  if (isSelfReferential(actor1, actor2)) {
    // "between Israel and Israel" is meaningless — say what it actually is.
    eventSentence = `GDELT recorded ${meaning} as a domestic event within ${actor1.trim()}.`;
  } else if (role === "Recipient") {
    eventSentence = `GDELT recorded ${country} as the recipient of ${meaning} from ${a1}.`;
  } else if (role === "Initiator") {
    eventSentence = `GDELT recorded ${country} as initiating ${meaning} directed at ${a2}.`;
  } else {
    eventSentence = `GDELT recorded ${meaning} between ${a1} and ${a2}.`;
  }

  const coverageLine =
    numArticles >= 100 ? `Covered across ${numArticles} news sources.` :
    numArticles >= 30  ? `Reported by ${numArticles} outlets.` :
    numArticles >= 5   ? `${numArticles} sources recorded this event.` : "";

  const scoreLine = `Goldstein score: ${score >= 0 ? "+" : ""}${score.toFixed(1)} (${tone}).`;

  const clusterLine = cluster ? `Clustered under: ${cluster}.` : "";

  // GDELT is known to miscode sports/entertainment coverage as violent
  // conflict — a city name (sports franchise) paired with a severe
  // conflict score and heavy coverage is a strong tell for this, and the
  // user should be warned rather than shown a confident-sounding sentence.
  const CONFLICT_TYPES = ["Fight", "Assault", "Mass Violence", "Coerce", "Exhibit Force"];
  const looksLikeMiscode =
    CONFLICT_TYPES.includes(eventType) && score <= -5 &&
    (numArticles >= 30 || /^[A-Z][a-z]+$/.test((a1 || "").trim()) || /^[A-Z][a-z]+$/.test((a2 || "").trim()));

  const cautionLine = looksLikeMiscode
    ? "⚠ This severity + a single-word actor name is a common pattern for GDELT miscoding sports or entertainment coverage as violent conflict — verify against the source link before treating this as a real event."
    : "";

  const caveat = "This could not be checked against the actual article, so treat it as GDELT's raw coding, not a confirmed account of what happened.";

  return [eventSentence, scoreLine, coverageLine, clusterLine, cautionLine, caveat].filter(Boolean).join(" ");
}

// Actors GDELT couldn't resolve read like "an unnamed monarch" or "an
// unidentified party from Bahrain" — grammatically fine, but they carry
// zero real information. For exactly these cases it's worth spending a
// Gemini call to pull the ACTUAL identity out of the source article,
// rather than for every event (keeps quota usage targeted, not blanket).
const GENERIC_ACTOR_MARKERS = ["unidentified", "unnamed", "unknown", "an actor", "unspecified", "bloc actor"];
function isGenericActor(name) {
  const n = (name || "").toLowerCase();
  return GENERIC_ACTOR_MARKERS.some((m) => n.includes(m));
}

// GDELT sometimes mis-tags BOTH sides of an event with the same country
// (e.g. "France -> France" for a story that's actually about France and
// Iran) — a coding error in GDELT's own raw data, not something rule-based
// normalization can catch, since the country-code fields are the exact
// thing that's wrong. Same-actor-on-both-sides is a strong enough signal
// to warrant automatic verification, same as a generic/unnamed actor.
function isSelfReferential(a1, a2) {
  const n1 = (a1 || "").trim().toLowerCase();
  const n2 = (a2 || "").trim().toLowerCase();
  return n1 && n2 && n1 === n2;
}

// Strips generic-role prefixing ("an unnamed", "an unspecified") down to
// the meaningful core of an actor name, for text-matching purposes.
function extractKeyToken(name) {
  if (!name) return "";
  return name.replace(/^(an|a|the)\s+(unnamed|unidentified|unspecified)\s*/i, "").trim();
}

// Free, local, no-API-call check: does the fetched headline actually
// mention either actor at all? This catches GDELT keyword-matching noise
// (an unrelated article about Switzerland attached to a Vietnam-Argentina
// event) regardless of whether the actor NAMES themselves look suspicious
// — unlike isGenericActor/isSelfReferential, which only catch cases where
// the actor label itself is the tell. Most noise cases involve two
// completely normal-looking country names with an unrelated article.
function headlineMentionsActor(headlineText, actorName) {
  if (!headlineText || !actorName) return false;
  const token = extractKeyToken(actorName);
  if (!token || isGenericActor(token)) return false; // can't text-match a generic label
  const h = headlineText.toLowerCase();
  if (h.includes(token.toLowerCase())) return true;
  // Fall back to individual significant words (handles "United Kingdom"
  // headline saying just "Britain", demonyms, etc.) — 5+ chars only, to
  // avoid false-matching on short common words.
  return token.split(/\s+/).filter(w => w.length >= 5).some(w => h.includes(w.toLowerCase()));
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Wraps every whole-word occurrence of any alias in <mark>. Mirrors the
// backend matcher: aliases over 3 chars are case-insensitive (optional
// plural "s"); short ones (US, UK, UAE) are case-sensitive.
function highlightTerms(text, aliases) {
  const uniq = [...new Set((aliases || []).filter(Boolean))].sort((a, b) => b.length - a.length);
  const long = uniq.filter((a) => a.length > 3).map(escapeRegex);
  const short = uniq.filter((a) => a.length <= 3).map(escapeRegex);
  const wrap = (parts, suffix) => `(?<![\\p{L}\\p{N}_])(?:${parts.join("|")})${suffix}(?![\\p{L}\\p{N}_])`;
  const regexes = [];
  if (long.length) regexes.push(new RegExp(wrap(long, "s?"), "giu"));
  if (short.length) regexes.push(new RegExp(wrap(short, ""), "gu"));
  if (regexes.length === 0) return text;

  const matches = regexes
    .flatMap((re) => [...text.matchAll(re)])
    .sort((a, b) => a.index - b.index || b[0].length - a[0].length);
  const out = [];
  let pos = 0;
  for (const m of matches) {
    if (m.index < pos) continue; // overlaps an earlier match
    if (m.index > pos) out.push(text.slice(pos, m.index));
    out.push(<mark key={m.index}>{m[0]}</mark>);
    pos = m.index + m[0].length;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

function prominenceLabel(t) {
  if (t.prominence === "central") return "central";
  if (t.prominence === "passing") return `passing mention (${t.count}x)`;
  if (t.prominence === "absent") return "not named";
  return "generic label — can't be matched by name";
}

// Links that mean the article doesn't show the actors interacting — worth
// an automatic AI check.
const WEAK_LINKS = ["listed", "one_sided", "none"];

// Compact relevance summary from /article-relevance: a colored dot plus
// the one-line verdict, and (optionally) the single best quoted sentence.
function RelevanceSummary({ data, showSnippet }) {
  if (!data) return null;
  const aliases = (data.terms || []).flatMap((t) => t.aliases || []);
  return (
    <>
      <div className="relevance-line">
        {data.link !== "unavailable" && <span className={`relevance-dot relevance-dot-${data.link}`} />}
        <span>{data.verdict_text}</span>
      </div>
      {showSnippet && data.best_snippet && (
        <p className="relevance-snippet">“{highlightTerms(data.best_snippet, aliases)}”</p>
      )}
    </>
  );
}

// Per-actor prominence with matching sentences, places and main topics —
// shown only after "More detail" is clicked.
function RelevanceDetail({ data, highlightTerm }) {
  if (!data) return null;
  const terms = [...(data.terms || [])];
  // List the clicked actor first.
  const hl = (highlightTerm || "").trim().toLowerCase();
  const isClicked = (t) =>
    t.term.toLowerCase() === hl || (t.aliases || []).some((a) => a.toLowerCase() === hl);
  if (hl && terms.length === 2 && !isClicked(terms[0]) && isClicked(terms[1])) terms.reverse();

  const places = data.named_places || [];
  const entities = data.main_entities || [];
  return (
    <div className="scan-relevance">
      {data.article_ok && terms.map((t, i) => (
        <div key={`${t.term}-${i}`} className="relevance-actor">
          <div className="relevance-actor-head">
            <span className="relevance-actor-name">{t.term}</span> — {prominenceLabel(t)}
          </div>
          {(t.snippets || []).map((s, j) => (
            <p key={j} className="scan-mentions-snippet">{highlightTerms(s, t.aliases)}</p>
          ))}
        </div>
      ))}
      {places.length > 0 && (
        <div className="relevance-meta">
          Places named in the article:{" "}
          {places.map((p) => (
            <span key={p.name} className="relevance-place-chip">{p.name} ({p.count})</span>
          ))}
        </div>
      )}
      {entities.length > 0 && (
        <div className="relevance-meta">
          Article is mainly about: {entities.map((e) => `${e.name} (${e.count}x)`).join(", ")}
        </div>
      )}
    </div>
  );
}

// Auto-loads article headline on mount, staggered by index to avoid
// hammering the backend. Shows immediately when loaded — no button needed.
// If either actor is generic, automatically follows up with AI
// verification to resolve the real name instead of stopping at the
// headline and requiring a manual "Verify with AI" click.
export default function ArticleScan({
  url, actor1, actor2, eventType, country,
  score, numArticles, role, cluster,
  autoLoad = false, loadDelay = 0,
  highlightTerm = "",
  onRelevance,
}) {
  const [state, setState] = useState(autoLoad ? "loading-headline" : "idle");
  const [headline, setHeadline] = useState(null);
  const [enriched, setEnriched] = useState(null);
  const [error, setError] = useState("");
  const [dataSummary, setDataSummary] = useState(null);
  const [relevance, setRelevance] = useState(null);
  const [relevanceFailed, setRelevanceFailed] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  // url the AI verification was last started for (auto or manual), so the
  // auto-verify effect below never fires twice for the same event.
  const verifiedForRef = useRef(null);
  const urlRef = useRef(url);
  urlRef.current = url;

  // Once the headline for THIS url has loaded, run the local relevance
  // analysis. Runs after (never before) the headline is shown, so it can't
  // delay it. `headline.forUrl` guards against firing on a stale headline
  // in the render where `url` has just changed but the reset below hasn't
  // landed yet. Resets whenever url / actor1 / actor2 change.
  const headlineReady = !!headline && headline.forUrl === url;
  const headlineText = headlineReady ? headline.headline : "";
  useEffect(() => {
    setRelevance(null);
    setRelevanceFailed(false);
    setShowDetail(false);
    if (!headlineReady) return;
    let cancelled = false;
    getArticleRelevance(url, actor1, actor2, headlineText)
      .then((data) => { if (!cancelled) setRelevance({ ...data, forUrl: url }); })
      .catch(() => { if (!cancelled) setRelevanceFailed(true); });
    return () => { cancelled = true; };
  }, [url, actor1, actor2, headlineReady]);
  const relevanceReady = !!relevance && relevance.forUrl === url;
  const link = relevanceReady ? relevance.link : null;

  // Tell the parent list (once per url + link) how the article relates.
  const reportedRef = useRef(null);
  useEffect(() => {
    if (!link || !onRelevance) return;
    const key = `${url}|${link}`;
    if (reportedRef.current === key) return;
    reportedRef.current = key;
    onRelevance(url, link);
  }, [url, link]);

  const needsIdentity = isGenericActor(actor1) || isGenericActor(actor2) || isSelfReferential(actor1, actor2);

  const runDeepScan = () => {
    const forUrl = url;
    verifiedForRef.current = forUrl;
    setError("");
    setState("loading-ai");
    enrichEvent({ url, actor1, actor2, event_type: eventType, country, score })
      .then((data) => {
        if (urlRef.current !== forUrl) return; // user moved on to another event
        // Only a real Gemini judgment (gdelt_match present) counts as verified.
        if (data.enriched && data.gdelt_match !== undefined && data.gdelt_match !== null) {
          setEnriched(data); setState("enriched");
        } else {
          setError(data.error || "AI verification could not complete"); setState("headline");
        }
      })
      .catch((e) => {
        if (urlRef.current !== forUrl) return;
        setError(e.message); setState("headline");
      });
  };

  // Auto-verify once the relevance link is in: listed / one_sided / none
  // is worth an AI check. If the relevance call failed (or the article text
  // was unavailable to it), fall back to the headline-text heuristic —
  // require BOTH actors to show up in the headline before trusting it (matching only one side, e.g. a
  // "Bahrain-Qatar" event whose headline is about India and Bahrain, isn't
  // strong enough evidence).
  useEffect(() => {
    if (!autoLoad || state !== "headline" || !headlineReady) return;
    if (verifiedForRef.current === url) return;
    if (relevanceReady && link !== "unavailable") {
      if (WEAK_LINKS.includes(link)) runDeepScan();
    } else if (relevanceFailed || relevanceReady) {
      const h = headline.headline;
      const looksUnrelated = !!h && !(headlineMentionsActor(h, actor1) && headlineMentionsActor(h, actor2));
      if (looksUnrelated) runDeepScan();
    }
  }, [state, relevanceReady, relevanceFailed, headlineReady]);

  useEffect(() => {
    if (!autoLoad || !url || !url.startsWith("http")) return;

    // Reset everything immediately — without this, switching to a new
    // event (new url) while an old headline/enrichment is still showing
    // would leave the stale content visible until the new fetch resolves,
    // and if the new fetch fails, the OLD event's data would incorrectly
    // stay on screen looking current.
    setHeadline(null);
    setEnriched(null);
    setError("");
    setDataSummary(null);
    setRelevance(null);
    setRelevanceFailed(false);
    setShowDetail(false);
    verifiedForRef.current = null;
    setState("loading-headline");

    const timer = setTimeout(() => {
      getArticleHeadline(url)
        .then((data) => {
          setHeadline({ ...data, forUrl: url });
          // Generic / self-referential actors always get AI verification.
          // Everything else shows the headline right away; the auto-verify
          // effect above decides once the relevance verdict (or, if that
          // call fails, the headline heuristic) is in.
          if (needsIdentity) { runDeepScan(); }
          else { setState("headline"); }
        })
        .catch((e) => {
          const summary = buildDataSummary({ actor1, actor2, score, country, numArticles, role, cluster, eventType });
          setDataSummary(summary);
          setError(e.message);
          setState("data-fallback");
        });
    }, loadDelay);
    return () => clearTimeout(timer);
  }, [url]);

  if (!url || !url.startsWith("http")) return null;

  const handleHeadline = () => {
    setState("loading-headline");
    getArticleHeadline(url)
      .then((data) => { setHeadline({ ...data, forUrl: url }); setState("headline"); })
      .catch((e) => {
        const summary = buildDataSummary({ actor1, actor2, score, country, numArticles, role, cluster, eventType });
        setDataSummary(summary);
        setError(e.message);
        setState("data-fallback");
      });
  };

  const handleDeepScan = runDeepScan;


  const isMismatch = enriched && enriched.gdelt_match === false;

  const detailToggle = relevanceReady && relevance.article_ok && (
    <button className="relevance-more" onClick={() => setShowDetail((v) => !v)}>
      {showDetail ? "Less detail" : "More detail"}
    </button>
  );

  // MIS-TAGGED — neither actor named: collapse to headline + verdict line
  // until "More detail" is clicked.
  const collapsed = link === "none" && !showDetail &&
    (state === "headline" || state === "loading-ai" || state === "enriched");
  if (collapsed) return (
    <div className="scan-result scan-result-collapsed">
      <div className="scan-result-label">
        📰 ARTICLE HEADLINE
        {headline?.domain && <span className="scan-source"> · {headline.domain}</span>}
      </div>
      {headline?.headline && <p className="scan-what-happened">{headline.headline}</p>}
      <RelevanceSummary data={relevance} showSnippet={false} />
      {detailToggle}
    </div>
  );

  // IDLE
  if (state === "idle") return (
    <button className="scan-btn" onClick={handleHeadline}>📰 Load article headline</button>
  );

  // LOADING — once the headline is in, AI verification runs underneath
  // it (see HEADLINE below) instead of replacing it with a spinner.
  if (state === "loading-headline" || (state === "loading-ai" && !headlineReady)) return (
    <div className="scan-loading">
      <span className="scan-spinner">◉</span>
      {state === "loading-headline" ? "Fetching article…" :
        needsIdentity ? "Resolving unnamed actor from article…" : "Running AI analysis…"}
    </div>
  );

  // DATA FALLBACK — article unreachable, so this is UNVERIFIED GDELT coding only
  if (state === "data-fallback") return (
    <div className="scan-result scan-result-data">
      <div className="scan-result-label">
        ⓘ ARTICLE UNAVAILABLE — SHOWING GDELT'S CODING ONLY
        <span className="scan-source"> · source article not accessible</span>
      </div>
      <p className="scan-what-happened">{dataSummary}</p>
    </div>
  );

  // HEADLINE
  const selfRef = isSelfReferential(actor1, actor2);
  if (state === "headline" || state === "loading-ai") return (
    <div className="scan-result">
      <div className="scan-result-label">
        📰 ARTICLE HEADLINE
        {headline?.domain && <span className="scan-source"> · {headline.domain}</span>}
      </div>
      {headline?.headline && <p className="scan-what-happened">{headline.headline}</p>}
      {relevanceReady ? (
        <RelevanceSummary data={relevance} showSnippet={true} />
      ) : !relevanceFailed && (
        <div className="relevance-meta">Checking how well the article supports this event…</div>
      )}
      {detailToggle}
      {relevanceReady && showDetail && <RelevanceDetail data={relevance} highlightTerm={highlightTerm} />}
      {(selfRef || !relevanceReady) && (
        <div className="scan-matched-note">
          {selfRef ? (
            <>⚠ GDELT coded both sides of this event as {actor1} — that's unusual and often
            means the actual other party wasn't correctly identified. Checking with AI now
            to confirm whether this is really a {actor1}-only event or something got missed.</>
          ) : (
            <>GDELT recorded this as the source for the {eventType || "event"} above
            {actor1 && actor2 ? ` between ${actor1} and ${actor2}` : ""} — if the headline
            doesn't obviously mention both, click "Verify with AI" to check the actual match.</>
          )}
        </div>
      )}
      {state === "headline" && error && (
        <div className="scan-ai-error">AI verification unavailable: {error}</div>
      )}
      <div className="scan-actions-row">
        {state === "loading-ai" ? (
          <div className="scan-loading">
            <span className="scan-spinner">◉</span>
            {needsIdentity ? "Resolving unnamed actor from article…" : "Running AI analysis…"}
          </div>
        ) : (
          <button className="scan-btn" onClick={handleDeepScan}>🤖 Verify with AI</button>
        )}
        {!autoLoad && state === "headline" && <button className="scan-btn-sm" onClick={() => setState("idle")}>dismiss</button>}
      </div>
    </div>
  );

  // ENRICHED
  const wasSelfReferential = isSelfReferential(actor1, actor2);
  const resolvedToDifferentActor = enriched && enriched.real_actor2 &&
    enriched.real_actor2.trim().toLowerCase() !== (actor2 || "").trim().toLowerCase();
  // Prefer the AI's direct judgment (it read the real article and was
  // asked explicitly which countries are really involved) over inferring
  // it indirectly from name changes — this catches cases like
  // "Manama -> Hamad Bin Isa Al Khalifa" where both sides are correctly
  // Bahraini by name, but a foreign country was still the real other party.
  const likelyMisscoped = enriched.is_actually_international === true ||
    (wasSelfReferential && resolvedToDifferentActor);
  const otherCountries = (enriched.countries_involved || []).filter(
    c => c && c.trim().toLowerCase() !== (country || "").trim().toLowerCase()
  );

  return (
    <div className={`scan-result ${isMismatch ? "scan-result-mismatch" : ""}`}>
      <div className="scan-result-label">
        {isMismatch ? "⚠ GDELT MISCLASSIFICATION DETECTED" : "🤖 AI VERIFIED"}
        {enriched.source && <span className="scan-source"> · {enriched.source}</span>}
      </div>
      {likelyMisscoped && (
        <div className="scan-mismatch-reason">
          ⚠ This was filed as a domestic {country || actor1} event, but the article shows
          {otherCountries.length > 0 ? ` ${otherCountries.join(", ")}` : " another country"} was
          also a real participant — this is likely miscategorized and should be treated as
          international, not domestic.
        </div>
      )}
      {isMismatch && enriched.mismatch_reason && (
        <div className="scan-mismatch-reason">{enriched.mismatch_reason}</div>
      )}
      {enriched.what_happened && <p className="scan-what-happened">{enriched.what_happened}</p>}
      {(enriched.real_actor1 !== actor1 || enriched.real_actor2 !== actor2 || enriched.location) && (
        <div className="scan-actors-row">
          {enriched.real_actor1 !== actor1 && (
            <span className="scan-actor-resolved">
              <span className="scan-actor-label">Actor 1</span>{enriched.real_actor1}
            </span>
          )}
          {enriched.real_actor2 !== actor2 && (
            <span className="scan-actor-resolved">
              <span className="scan-actor-label">Actor 2</span>{enriched.real_actor2}
            </span>
          )}
          {enriched.location && (
            <span className="scan-actor-resolved">
              <span className="scan-actor-label">Location</span>{enriched.location}
            </span>
          )}
        </div>
      )}
      {enriched.key_detail && !isMismatch && (
        <p className="scan-key-detail">📌 {enriched.key_detail}</p>
      )}
      {relevanceReady && <RelevanceSummary data={relevance} showSnippet={false} />}
      {detailToggle}
      {relevanceReady && showDetail && <RelevanceDetail data={relevance} highlightTerm={highlightTerm} />}
      {!autoLoad && (
        <button className="scan-btn-sm" onClick={() => setState("idle")} style={{ marginTop: 6 }}>
          dismiss
        </button>
      )}
    </div>
  );
}
