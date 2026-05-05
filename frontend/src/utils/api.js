import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

// Admin key is injected at build time from VITE_API_KEY env var.
// Never shown to the user — never typed manually.
const ADMIN_KEY = import.meta.env.VITE_API_KEY || ''

const api = axios.create({ baseURL: BASE })

export const generatePlan  = (spec) => api.post('/plan', spec).then(r => r.data)

export const persistRouter = (spec) =>
  api.post('/admin/routers', spec, {
    headers: ADMIN_KEY ? { 'X-API-Key': ADMIN_KEY } : {},
  }).then(r => r.data)

export const getHealth           = () => api.get('/health').then(r => r.data)
export const getRouters          = () => api.get('/graph/routers').then(r => r.data)
export const getRouterChain      = (id) => api.get(`/graph/router/${id}/chain`).then(r => r.data)
export const getGraphData        = () => api.get('/graph/data').then(r => r.data)
export const getGraphNodes       = () => api.get('/graph/nodes').then(r => r.data)
export const getGraphPath        = (sourceId, targetId) =>
  api.get('/graph/path', { params: { source_id: sourceId, target_id: targetId } }).then(r => r.data)
export const explainRelationship = (nodes, edges) =>
  api.post('/graph/explain', { nodes, edges }, {
    headers: ADMIN_KEY ? { 'X-API-Key': ADMIN_KEY } : {},
  }).then(r => r.data)
