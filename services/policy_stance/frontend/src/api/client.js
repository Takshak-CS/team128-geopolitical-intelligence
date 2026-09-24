import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const client = axios.create({
  baseURL: API_BASE,
});

export const uploadFiles = async (files, trainGnn = false) => {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  const response = await client.post(`/upload?train_gnn=${trainGnn}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const fetchSimilarity = async (params) => (await client.get('/similarity', { params })).data;
export const fetchGraph = async (params) => (await client.get('/graph', { params })).data;
export const fetchClusters = async (params) => (await client.get('/clusters', { params })).data;
export const fetchTimeline = async (params) => (await client.get('/timeline', { params })).data;
export const fetchInsights = async (params) => (await client.get('/insights', { params })).data;
export const fetchGnn = async (params) => (await client.get('/gnn', { params })).data;
