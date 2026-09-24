import { useEffect, useMemo, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { getAllianceBlocs, getCountries, getDatasets, getGraph, getIssues, getStatus, getTopics } from './api';
import AppShell from './components/AppShell';
import BlocsPage from './pages/BlocsPage';
import ComparePage from './pages/ComparePage';
import DashboardPage from './pages/DashboardPage';
import GraphPage from './pages/GraphPage';
import HeatmapsPage from './pages/HeatmapsPage';
import PolicyStancePage from './pages/PolicyStancePage';
import TemporalPage from './pages/TemporalPage';

export default function App() {
  const [status, setStatus] = useState({ ready: false, progress: 'Starting', node_count: 0, edge_count: 0, dataset_count: 0 });
  const [countries, setCountries] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [issues, setIssues] = useState([]);
  const [topics, setTopics] = useState([]);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [blocs, setBlocs] = useState({ country_to_bloc: {}, blocs: [] });

  useEffect(() => {
    let cancelled = false;
    const loadStatus = async () => {
      try {
        const data = await getStatus();
        if (!cancelled) {
          setStatus(data);
        }
      } catch (error) {
        if (!cancelled) {
          setStatus((current) => ({ ...current, progress: 'Backend unavailable' }));
        }
      }
    };

    loadStatus();
    const interval = window.setInterval(loadStatus, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!status.ready) return;
    Promise.all([getCountries(), getDatasets(), getIssues(), getTopics(), getGraph(), getAllianceBlocs()])
      .then(([countryData, datasetData, issueData, topicData, graphData, blocData]) => {
        setCountries(countryData);
        setDatasets(datasetData);
        setIssues(issueData);
        setTopics(topicData);
        setGraph(graphData);
        setBlocs(blocData);
      })
      .catch(() => undefined);
  }, [status.ready]);

  const blocMap = useMemo(() => blocs.country_to_bloc || {}, [blocs]);

  return (
    <AppShell status={status}>
      <Routes>
        <Route path="/" element={<DashboardPage status={status} countries={countries} datasets={datasets} graph={graph} blocMap={blocMap} />} />
        <Route path="/graph" element={<GraphPage status={status} blocMap={blocMap} />} />
        <Route path="/compare" element={<ComparePage countries={countries} />} />
        <Route path="/heatmaps" element={<HeatmapsPage />} />
        <Route path="/temporal" element={<TemporalPage countries={countries} status={status} blocMap={blocMap} />} />
        <Route path="/blocs" element={<BlocsPage />} />
        <Route path="/policy-stance" element={<PolicyStancePage countries={countries} issues={issues} topics={topics} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
