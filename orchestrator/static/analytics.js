// Analytics tracker + founder dashboard.
//
//   <script src="/static/analytics.js" data-page="home" defer></script>
//
// Auto-fires a page_view on load. Exposes window.geoTrack(event, label)
// for manual tracking from any page.
//
// Founder dashboard: same pin as reviews (e.g. "santhosh").
// Shows unique visitors, page views, top clicks, top countries, daily chart.

(() => {
  const script = document.currentScript;
  const PAGE = script?.dataset.page || document.location.pathname.replace(/^\//, "") || "home";
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  // ── fire & forget event ───────────────────────────────────────────────────
  function track(event, label = "") {
    fetch("/analytics/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: PAGE, event, label: String(label).slice(0, 128) }),
    }).catch(() => {});
  }

  // expose globally so other page scripts can call window.geoTrack(...)
  window.geoTrack = track;

  // auto page view
  track("page_view");

  // ── passive click tracker ─────────────────────────────────────────────────
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-track]");
    if (!el) return;
    track("click", el.dataset.track);
  }, { passive: true });

  // ── styles ────────────────────────────────────────────────────────────────
  const css = `
  .an-fab { position:fixed; left:18px; bottom:18px; z-index:60; border:0; border-radius:999px;
    padding:11px 18px; font:700 13px ${FONT}; cursor:pointer; color:#e6ebf3;
    background:linear-gradient(135deg,rgba(14,165,233,.92),rgba(6,182,212,.92));
    box-shadow:0 10px 28px rgba(14,165,233,.4); display:flex; align-items:center; gap:8px; }
  .an-fab:hover { transform:translateY(-1px); }
  .an-fab .dot { width:8px;height:8px;border-radius:50%;background:#4ade80;
    box-shadow:0 0 6px #4ade80; display:inline-block; }

  .an-pin-dialog { border:1px solid #2a3850; border-radius:14px; padding:0;
    width:min(360px,92vw); background:#0f1622; color:#e6ebf3; font-family:${FONT}; }
  .an-pin-dialog::backdrop { background:rgba(3,6,12,.78); backdrop-filter:blur(4px); }
  .an-pin-form { padding:22px 22px 18px; display:grid; gap:14px; }
  .an-pin-form h3 { margin:0; font-size:17px; }
  .an-pin-form p  { margin:0; color:#a7b1c2; font-size:13px; }
  .an-pin-input { font:15px ${FONT}; color:#e6ebf3; background:#0b111b;
    border:1px solid #2a3850; border-radius:10px; padding:10px 12px;
    width:100%; box-sizing:border-box; letter-spacing:2px; }
  .an-pin-input:focus { outline:none; border-color:#38bdf8; }
  .an-pin-err { color:#f87171; font-size:13px; min-height:18px; }
  .an-pin-actions { display:flex; gap:10px; justify-content:flex-end; }
  .an-ghost { background:transparent; color:#a7b1c2; border:1px solid #2a3850;
    border-radius:10px; padding:10px 16px; cursor:pointer; font:14px ${FONT}; }
  .an-btn { border:0; border-radius:12px; padding:11px 20px; font:700 14px ${FONT};
    cursor:pointer; color:#0a1628;
    background:linear-gradient(135deg,#38bdf8,#06b6d4); }

  .an-panel-dialog { border:1px solid #2a3850; border-radius:20px; padding:0;
    width:min(780px,96vw); max-height:90vh; overflow-y:auto;
    background:#0a1220; color:#e6ebf3; font-family:${FONT}; }
  .an-panel-dialog::backdrop { background:rgba(3,6,12,.82); backdrop-filter:blur(5px); }
  .an-panel { padding:24px 26px 28px; display:grid; gap:20px; }
  .an-panel h2 { margin:0; font-size:20px; }
  .an-panel .sub { color:#a7b1c2; font-size:13px; margin:0; }
  .an-close { float:right; background:none; border:0; color:#a7b1c2;
    font-size:22px; cursor:pointer; line-height:1; }

  .an-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }
  .an-stat { background:#0f1a2e; border:1px solid #1e2d44; border-radius:14px;
    padding:16px 18px; }
  .an-stat .big { font-size:28px; font-weight:800; color:#38bdf8; line-height:1; }
  .an-stat .lbl { font-size:12px; color:#a7b1c2; margin-top:4px; }

  .an-section { background:#0f1a2e; border:1px solid #1e2d44; border-radius:14px; padding:16px 18px; }
  .an-section h4 { margin:0 0 12px; font-size:14px; color:#94a3b8; text-transform:uppercase; letter-spacing:.5px; }
  .an-row { display:flex; justify-content:space-between; align-items:center;
    padding:7px 0; border-bottom:1px solid #1a2640; font-size:14px; }
  .an-row:last-child { border-bottom:0; }
  .an-row .name { color:#e6ebf3; }
  .an-row .cnt { color:#38bdf8; font-weight:700; font-size:15px; }
  .an-bar-wrap { flex:1; margin:0 12px; height:6px; background:#1a2640; border-radius:3px; overflow:hidden; }
  .an-bar { height:100%; border-radius:3px; background:linear-gradient(90deg,#38bdf8,#06b6d4); }

  .an-chart { display:flex; align-items:flex-end; gap:6px; height:80px; }
  .an-col-wrap { display:flex; flex-direction:column; align-items:center; gap:4px; flex:1; }
  .an-col { background:linear-gradient(180deg,#38bdf8,#0ea5e9); border-radius:3px 3px 0 0;
    width:100%; min-height:2px; }
  .an-col-lbl { font-size:10px; color:#64748b; white-space:nowrap; }

  .an-recent { font-size:12px; }
  .an-ev { display:flex; gap:8px; padding:5px 0; border-bottom:1px solid #1a2640; }
  .an-ev:last-child { border-bottom:0; }
  .an-ev .ts { color:#64748b; white-space:nowrap; }
  .an-ev .pg { color:#a78bfa; }
  .an-ev .et { color:#38bdf8; }
  .an-ev .lb { color:#94a3b8; }
  `;
  const styleEl = document.createElement("style");
  styleEl.textContent = css;
  document.head.append(styleEl);

  const make = (tag, attrs = {}, text) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text != null) el.textContent = text;
    return el;
  };

  // ── FAB button ─────────────────────────────────────────────────────────────
  const fab = make("button", { class: "an-fab", type: "button", title: "Analytics (Founder)" });
  fab.innerHTML = `<span class="dot"></span> Analytics`;

  // ── PIN dialog ─────────────────────────────────────────────────────────────
  const pinDlg = make("dialog", { class: "an-pin-dialog" });
  const pinForm = make("form", { class: "an-pin-form", method: "dialog", novalidate: "" });
  const pinErr = make("div", { class: "an-pin-err" });
  const pinInput = make("input", {
    class: "an-pin-input", type: "password",
    placeholder: "Enter founder pin", autocomplete: "off", maxlength: "30",
  });
  const pinCancel = make("button", { type: "button", class: "an-ghost" }, "Cancel");
  const pinSubmit = make("button", { type: "submit", class: "an-btn" }, "Unlock");
  const pinActions = make("div", { class: "an-pin-actions" });
  pinActions.append(pinCancel, pinSubmit);
  pinForm.append(
    make("h3", {}, "📊 Analytics — Founder Access"),
    make("p", {}, "Enter your founder pin to view site analytics."),
    pinInput, pinErr, pinActions,
  );
  pinDlg.append(pinForm);
  pinCancel.addEventListener("click", () => { pinDlg.close(); pinErr.textContent = ""; pinInput.value = ""; });

  // ── Dashboard dialog ───────────────────────────────────────────────────────
  const dashDlg = make("dialog", { class: "an-panel-dialog" });
  const dashPanel = make("div", { class: "an-panel" });
  dashDlg.append(dashPanel);

  function fmt(n) { return n >= 1000 ? `${(n/1000).toFixed(1)}k` : String(n); }

  function renderDash(data, allEvents) {
    dashPanel.replaceChildren();

    const closeBtn = make("button", { class: "an-close", type: "button", "aria-label": "Close" }, "×");
    closeBtn.addEventListener("click", () => dashDlg.close());
    const hdr = make("div");
    hdr.innerHTML = `<h2 style="display:inline">📊 Site Analytics</h2>`;
    hdr.append(closeBtn);
    const sub = make("p", { class: "sub" }, `Live data from deployment · ${data.total_events.toLocaleString()} total events`);
    dashPanel.append(hdr, sub);

    // ── stat tiles
    const stats = make("div", { class: "an-stats" });
    const tiles = [
      { big: fmt(data.unique_visitors), lbl: "Unique Visitors" },
      { big: fmt(data.page_views), lbl: "Page Views" },
      { big: fmt(data.queries_submitted), lbl: "Queries Run" },
      { big: fmt(data.total_events), lbl: "Total Events" },
    ];
    tiles.forEach(({ big, lbl }) => {
      const tile = make("div", { class: "an-stat" });
      tile.append(make("div", { class: "big" }, big), make("div", { class: "lbl" }, lbl));
      stats.append(tile);
    });
    dashPanel.append(stats);

    // ── daily views chart
    const dailyData = data.daily_views_7d || {};
    const days = Object.keys(dailyData).sort();
    if (days.length) {
      const sec = make("div", { class: "an-section" });
      sec.append(make("h4", {}, "Page Views — Last 7 Days"));
      const chart = make("div", { class: "an-chart" });
      const max = Math.max(...Object.values(dailyData), 1);
      days.forEach(d => {
        const v = dailyData[d] || 0;
        const colWrap = make("div", { class: "an-col-wrap" });
        const col = make("div", { class: "an-col" });
        col.style.height = `${Math.max(2, Math.round((v / max) * 72))}px`;
        col.title = `${v} views`;
        const lbl = make("div", { class: "an-col-lbl" }, d.slice(5)); // MM-DD
        colWrap.append(col, lbl);
        chart.append(colWrap);
      });
      sec.append(chart);
      dashPanel.append(sec);
    }

    // ── page views by page + events by type side by side
    const grid2 = make("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:12px;" });

    const byPage = make("div", { class: "an-section" });
    byPage.append(make("h4", {}, "Views by Page"));
    const pageEntries = Object.entries(data.by_page || {}).sort((a,b) => b[1]-a[1]);
    const pageMax = pageEntries[0]?.[1] || 1;
    pageEntries.slice(0, 8).forEach(([page, cnt]) => {
      const row = make("div", { class: "an-row" });
      const bar = make("div", { class: "an-bar" });
      bar.style.width = `${Math.round((cnt/pageMax)*100)}%`;
      const barWrap = make("div", { class: "an-bar-wrap" });
      barWrap.append(bar);
      row.append(make("span", { class: "name" }, page), barWrap, make("span", { class: "cnt" }, cnt));
      byPage.append(row);
    });
    grid2.append(byPage);

    const byEvent = make("div", { class: "an-section" });
    byEvent.append(make("h4", {}, "Event Types"));
    const eventEntries = Object.entries(data.by_event || {}).sort((a,b) => b[1]-a[1]);
    const evMax = eventEntries[0]?.[1] || 1;
    eventEntries.slice(0, 8).forEach(([evt, cnt]) => {
      const row = make("div", { class: "an-row" });
      const bar = make("div", { class: "an-bar" });
      bar.style.width = `${Math.round((cnt/evMax)*100)}%`;
      bar.style.background = "linear-gradient(90deg,#a78bfa,#ec4899)";
      const barWrap = make("div", { class: "an-bar-wrap" });
      barWrap.append(bar);
      row.append(make("span", { class: "name" }, evt), barWrap, make("span", { class: "cnt" }, cnt));
      byEvent.append(row);
    });
    grid2.append(byEvent);
    dashPanel.append(grid2);

    // ── top clicks + top countries side by side
    const grid3 = make("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:12px;" });

    const clicks = make("div", { class: "an-section" });
    clicks.append(make("h4", {}, "Top Clicks"));
    if ((data.top_clicks || []).length) {
      const clickMax = data.top_clicks[0].count;
      data.top_clicks.forEach(({ label, count }) => {
        const row = make("div", { class: "an-row" });
        const bar = make("div", { class: "an-bar" });
        bar.style.width = `${Math.round((count/clickMax)*100)}%`;
        bar.style.background = "linear-gradient(90deg,#f5b942,#f472b6)";
        const barWrap = make("div", { class: "an-bar-wrap" });
        barWrap.append(bar);
        row.append(make("span", { class: "name" }, label), barWrap, make("span", { class: "cnt" }, count));
        clicks.append(row);
      });
    } else {
      clicks.append(make("div", { style: "color:#64748b;font-size:13px;" }, "No click data yet."));
    }
    grid3.append(clicks);

    const countries = make("div", { class: "an-section" });
    countries.append(make("h4", {}, "Top Countries Explored"));
    if ((data.top_countries || []).length) {
      const ctryMax = data.top_countries[0].count;
      data.top_countries.forEach(({ country, count }) => {
        const row = make("div", { class: "an-row" });
        const bar = make("div", { class: "an-bar" });
        bar.style.width = `${Math.round((count/ctryMax)*100)}%`;
        bar.style.background = "linear-gradient(90deg,#34d399,#06b6d4)";
        const barWrap = make("div", { class: "an-bar-wrap" });
        barWrap.append(bar);
        row.append(make("span", { class: "name" }, country), barWrap, make("span", { class: "cnt" }, count));
        countries.append(row);
      });
    } else {
      countries.append(make("div", { style: "color:#64748b;font-size:13px;" }, "No country click data yet."));
    }
    grid3.append(countries);
    dashPanel.append(grid3);

    // ── recent events
    if (allEvents && allEvents.length) {
      const recent = make("div", { class: "an-section an-recent" });
      recent.append(make("h4", {}, `Recent Events (last ${Math.min(allEvents.length, 50)})`));
      allEvents.slice(0, 50).forEach(ev => {
        const row = make("div", { class: "an-ev" });
        row.append(
          make("span", { class: "ts" }, ev.created_at?.slice(0, 16).replace("T", " ") || ""),
          make("span", { class: "pg" }, ev.page),
          make("span", { class: "et" }, ev.event),
          ev.label ? make("span", { class: "lb" }, `· ${ev.label}`) : "",
        );
        recent.append(row);
      });
      dashPanel.append(recent);
    }
  }

  // ── pin form submit ────────────────────────────────────────────────────────
  pinForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    pinErr.textContent = "";
    pinSubmit.disabled = true;
    pinSubmit.textContent = "Loading…";
    try {
      const pin = encodeURIComponent(pinInput.value);
      const [sumRes, allRes] = await Promise.all([
        fetch("/analytics/summary"),
        fetch(`/analytics/all?pin=${pin}`),
      ]);
      if (!allRes.ok) {
        const err = await allRes.json().catch(() => ({}));
        throw new Error(err.detail || "Invalid pin.");
      }
      const sumData = await sumRes.json();
      const allData = await allRes.json();
      pinDlg.close();
      pinInput.value = "";
      renderDash(sumData, allData.events || []);
      dashDlg.showModal();
    } catch (err) {
      pinErr.textContent = err.message;
    } finally {
      pinSubmit.disabled = false;
      pinSubmit.textContent = "Unlock";
    }
  });

  fab.addEventListener("click", () => {
    pinErr.textContent = "";
    pinInput.value = "";
    pinDlg.showModal();
    setTimeout(() => pinInput.focus(), 50);
  });

  const mount = () => {
    document.body.append(fab, pinDlg, dashDlg);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
