import { useState, useEffect } from "react";
import { getArticleHeadline, enrichEvent } from "../api";

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
  if (role === "Recipient") {
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

// Auto-loads article headline on mount, staggered by index to avoid
// hammering the backend. Shows immediately when loaded — no button needed.
// If either actor is generic, automatically follows up with AI
// verification to resolve the real name instead of stopping at the
// headline and requiring a manual "Verify with AI" click.
export default function ArticleScan({
  url, actor1, actor2, eventType, country,
  score, numArticles, role, cluster,
  autoLoad = false, loadDelay = 0,
}) {
  const [state, setState] = useState(autoLoad ? "loading-headline" : "idle");
  const [headline, setHeadline] = useState(null);
  const [enriched, setEnriched] = useState(null);
  const [error, setError] = useState("");
  const [dataSummary, setDataSummary] = useState(null);

  const needsIdentity = isGenericActor(actor1) || isGenericActor(actor2) || isSelfReferential(actor1, actor2);

  const runDeepScan = () => {
    setState("loading-ai");
    enrichEvent({ url, actor1, actor2, event_type: eventType, country, score })
      .then((data) => {
        if (data.enriched) { setEnriched(data); setState("enriched"); }
        else { setError(data.error || "Could not enrich"); setState("headline"); }
      })
      .catch((e) => { setError(e.message); setState("headline"); });
  };

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
    setState("loading-headline");

    const timer = setTimeout(() => {
      getArticleHeadline(url)
        .then((data) => {
          setHeadline(data);
          const mentionsA1 = headlineMentionsActor(data.headline, actor1);
          const mentionsA2 = headlineMentionsActor(data.headline, actor2);
          // Require BOTH actors to show up in the headline before trusting
          // it as a correct match. Matching only one side (e.g. a
          // "Bahrain-Qatar" event where the headline is actually about
          // India and Bahrain — "Bahrain" matches by coincidence, "Qatar"
          // never appears) isn't strong enough evidence; the other actor
          // may be entirely miscoded. Self-referential pairs (actor1 ===
          // actor2) trivially satisfy this and are already separately
          // caught by needsIdentity anyway.
          const looksUnrelated = !!data.headline && !(mentionsA1 && mentionsA2);
          if (needsIdentity || looksUnrelated) { runDeepScan(); }
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
      .then((data) => { setHeadline(data); setState("headline"); })
      .catch((e) => {
        const summary = buildDataSummary({ actor1, actor2, score, country, numArticles, role, cluster, eventType });
        setDataSummary(summary);
        setError(e.message);
        setState("data-fallback");
      });
  };

  const handleDeepScan = runDeepScan;


  const isMismatch = enriched && enriched.gdelt_match === false;

  // IDLE
  if (state === "idle") return (
    <button className="scan-btn" onClick={handleHeadline}>📰 Load article headline</button>
  );

  // LOADING
  if (state === "loading-headline" || state === "loading-ai") return (
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
  if (state === "headline") return (
    <div className="scan-result">
      <div className="scan-result-label">
        📰 ARTICLE HEADLINE
        {headline?.domain && <span className="scan-source"> · {headline.domain}</span>}
      </div>
      {headline?.headline && <p className="scan-what-happened">{headline.headline}</p>}
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
      <div className="scan-actions-row">
        <button className="scan-btn" onClick={handleDeepScan}>🤖 Verify with AI</button>
        {!autoLoad && <button className="scan-btn-sm" onClick={() => setState("idle")}>dismiss</button>}
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
      {!autoLoad && (
        <button className="scan-btn-sm" onClick={() => setState("idle")} style={{ marginTop: 6 }}>
          dismiss
        </button>
      )}
    </div>
  );
}
