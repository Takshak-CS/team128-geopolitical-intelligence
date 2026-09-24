import axios from 'axios';

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

const client = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
});

export async function getStatus() {
  const { data } = await client.get('/status');
  return data;
}

export async function getGraph(year) {
  const { data } = await client.get(year ? `/graph/${year}` : '/graph');
  return data;
}

export async function getCountries() {
  const { data } = await client.get('/countries');
  return data;
}

export async function getCountry(name) {
  const { data } = await client.get(`/country/${encodeURIComponent(name)}`);
  return data;
}

export async function getSimilarity() {
  const { data } = await client.get('/similarity');
  return data;
}

export async function getTemporalAgreement() {
  const { data } = await client.get('/temporal-agreement');
  return data;
}

export async function getVotingAgreementMatrix() {
  const { data } = await client.get('/voting-agreement-matrix');
  return data;
}

export async function getAllianceBlocs() {
  const { data } = await client.get('/alliance-blocs');
  return data;
}

export async function getChord() {
  const { data } = await client.get('/chord');
  return data;
}

export async function getEmbeddings2d() {
  const { data } = await client.get('/embeddings/2d');
  return data;
}

export async function getEmbeddings3d() {
  const { data } = await client.get('/embeddings/3d');
  return data;
}

export async function getDatasets() {
  const { data } = await client.get('/datasets');
  return data;
}

export async function getIssues() {
  const { data } = await client.get('/issues');
  return data;
}

export async function getCompare(countryA, countryB) {
  const { data } = await client.get('/compare', { params: { country_a: countryA, country_b: countryB } });
  return data;
}

export async function getTimeline(countries, metric) {
  const { data } = await client.get('/timeline', { params: { countries: countries.join(','), metric } });
  return data;
}

export async function getPolicyStance(countries, issues, topic) {
  const { data } = await client.get('/policy-stance', { params: { countries: countries.join(','), issues: issues.join(','), topic } });
  return data;
}

export async function getTopics() {
  const { data } = await client.get('/topics');
  return data;
}

export async function getForecast(countries, metric = 'conflicts', horizon = 5) {
  const { data } = await client.get('/forecast', { params: { countries: countries.join(','), metric, horizon } });
  return data;
}

export async function getGraphDelta(year) {
  const { data } = await client.get(`/graph-delta/${year}`);
  return data;
}

export async function getBlocsByYear(year) {
  const { data } = await client.get(`/blocs-by-year/${year}`);
  return data;
}

export async function getCompareInsight(countryA, countryB) {
  const { data } = await client.get('/compare-insight', { params: { country_a: countryA, country_b: countryB } });
  return data;
}
