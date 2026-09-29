import { useEffect, useState, useMemo } from "react";
import "./App.css";
import { getHealth, getCachedDates, getCountries } from "./api";
import PipelineRunner from "./components/PipelineRunner.jsx";
import Hero from "./components/Hero.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import MetricsGrid from "./components/MetricsGrid.jsx";
import WorldMap from "./components/WorldMap.jsx";
import PartnerPanel from "./components/PartnerPanel.jsx";
import ChartsPanel from "./components/ChartsPanel.jsx";
import NetworkGraph from "./components/NetworkGraph.jsx";
import TopEventsWire from "./components/TopEventsWire.jsx";
import ActorExplorer from "./components/ActorExplorer.jsx";
import EventsTable from "./components/EventsTable.jsx";
import BriefingPanel from "./components/BriefingPanel.jsx";
import DomesticPanel from "./components/DomesticPanel.jsx";

export default function App() {
  const [health, setHealth] = useState(null);
  const [cachedDates, setCachedDates] = useState([]);

  const [date, setDate] = useState("");
  const [countries, setCountries] = useState([]);
  const [countriesLoading, setCountriesLoading] = useState(false);
  const [countriesError, setCountriesError] = useState("");
  const [countryCode, setCountryCode] = useState("");

  const [result, setResult] = useState(null);
  const [scope, setScope] = useState("international");
  const [selectedPartner, setSelectedPartner] = useState(null);
  const [selectedActor, setSelectedActor] = useState(null);

  // Load health + cached dates once on mount.
  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    getCachedDates()
      .then((d) => setCachedDates(d.dates || []))
      .catch(() => setCachedDates([]));
  }, []);

  // Whenever a complete 8-digit date is entered, look up which countries
  // actually appear in that day's file.
  useEffect(() => {
    if (!/^\d{8}$/.test(date)) {
      setCountries([]);
      setCountryCode("");
      return;
    }
    let cancelled = false;
    setCountriesLoading(true);
    setCountriesError("");
    setResult(null);

    getCountries(date)
      .then((data) => {
        if (cancelled) return;
        setCountries(data.countries || []);
        setCountryCode("");
      })
      .catch((err) => {
        if (cancelled) return;
        setCountries([]);
        setCountriesError(err.message);
      })
      .finally(() => {
        if (!cancelled) setCountriesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [date]);

  // Split the full event table by scope ONCE per result, so WorldMap,
  // NetworkGraph, ActorExplorer, and PartnerPanel all see only the rows
  // that belong to whichever tab is active — previously they all received
  // the full unfiltered table regardless of the International/Domestic
  // toggle, which is why domestic events (e.g. "UK -> London") showed up
  // mixed into the "International" network graph.
  const { internationalRows, domesticRows } = useMemo(() => {
    const rows = result?.table || [];
    const cc = result?.country_code;
    if (!cc) return { internationalRows: rows, domesticRows: [] };
    const isDomestic = (r) =>
      r.Actor1CountryCode && r.Actor1CountryCode === r.Actor2CountryCode && r.Actor1CountryCode === cc;
    return {
      internationalRows: rows.filter((r) => !isDomestic(r)),
      domesticRows: rows.filter(isDomestic),
    };
  }, [result]);

  return (
    <div className="page">
      <Hero health={health} result={result} />

      <main className="container">
        <ControlPanel
          date={date}
          onDateChange={setDate}
          cachedDates={cachedDates}
          countries={countries}
          countriesLoading={countriesLoading}
          countriesError={countriesError}
          countryCode={countryCode}
          onCountryChange={setCountryCode}
        />

        <PipelineRunner
          date={date}
          countryCode={countryCode}
          onResult={(r) => { setResult(r); }}
          disabled={!date || !countryCode}
        />

        {result && (
          <div className="results">
            {/* Scope toggle: International vs Domestic */}
            <div className="scope-toggle">
              <button
                className={`scope-btn ${scope === "international" ? "active" : ""}`}
                onClick={() => setScope("international")}
              >
                🌍 International
                <span className="scope-count">{internationalRows.length} events</span>
              </button>
              <button
                className={`scope-btn ${scope === "domestic" ? "active" : ""}`}
                onClick={() => setScope("domestic")}
              >
                🏠 Domestic
                <span className="scope-count">{domesticRows.length} events</span>
              </button>
            </div>

            {scope === "domestic" ? (
              <>
                <DomesticPanel domestic={result.domestic} countryName={result.country_name} />

                <NetworkGraph
                  tableRows={domesticRows}
                  countryCode={result.country_code}
                  countryName={result.country_name}
                  onNodeClick={(actor) => { setSelectedActor(actor); setSelectedPartner(null); }}
                />

                <div id="actor-explorer">
                  <ActorExplorer
                    actor={selectedActor}
                    tableRows={domesticRows}
                    countryName={result.country_name}
                    date={result.date}
                    onClear={() => setSelectedActor(null)}
                  />
                </div>
              </>
            ) : (
            <>
            <WorldMap
              countryCode={result.country_code}
              countryName={result.country_name}
              partners={result.partners}
              tableRows={internationalRows}
              onPartnerClick={(p) => setSelectedPartner(p)}
            />

            {selectedPartner && (
              <PartnerPanel
                partner={selectedPartner}
                tableRows={internationalRows}
                date={result.date}
                countryCode={result.country_code}
                countryName={result.country_name}
                onClose={() => setSelectedPartner(null)}
                onRunAnalysis={(r) => { setResult(r); setSelectedPartner(null); }}
              />
            )}

            <MetricsGrid metrics={result.metrics} />

            <ChartsPanel
              eventTypeCounts={result.event_type_counts}
              toneCounts={result.tone_counts}
              sentimentCounts={result.sentiment_counts}
              clusterCounts={result.cluster_counts}
              clusterQuality={result.cluster_quality}
            />

            <NetworkGraph
              tableRows={internationalRows}
              countryCode={result.country_code}
              countryName={result.country_name}
              onNodeClick={(actor) => { setSelectedActor(actor); setSelectedPartner(null); }}
            />

            <div id="actor-explorer">
              <ActorExplorer
                actor={selectedActor}
                tableRows={internationalRows}
                countryName={result.country_name}
                date={result.date}
                onClear={() => setSelectedActor(null)}
              />
            </div>

            <EventsTable
              rows={result.table}
              shown={result.table_rows_shown}
              total={result.table_rows_total}
            />

            </>)}

            <BriefingPanel result={result} internationalRows={internationalRows} domesticRows={domesticRows} scope={scope} />
          </div>
        )}
      </main>
    </div>
  );
}
