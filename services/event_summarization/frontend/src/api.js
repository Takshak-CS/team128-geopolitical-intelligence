export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (err) {
    throw new Error(
      `Could not reach the backend at ${API_BASE}. Is uvicorn running?`
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* response wasn't JSON, fall back to statusText */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return res.json();
}

export const getHealth = () => request("/health");
export const getCachedDates = () => request("/dates");
export const getCountries = (date) =>
  request(`/countries?date=${encodeURIComponent(date)}`);
export const analyze = (date, countryCode) =>
  request("/analyze", {
    method: "POST",
    body: JSON.stringify({ date, country_code: countryCode }),
  });
export const generateBriefing = (date, countryCode, force = false) =>
  request("/briefing", {
    method: "POST",
    body: JSON.stringify({ date, country_code: countryCode, force }),
  });

export const enrichEvent = (data) =>
  request("/enrich-event", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const getArticleHeadline = (url) =>
  request(`/article-headline?url=${encodeURIComponent(url)}`);

export const getHistoricalContext = (cc1, cc2) =>
  request(`/historical-context?cc1=${encodeURIComponent(cc1)}&cc2=${encodeURIComponent(cc2)}`);
