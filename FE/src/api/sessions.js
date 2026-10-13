import api from './axios'

export const getSessions = (params) => api.get('/sessions/', { params })
export const getSession = (id) => api.get(`/sessions/${id}`)
export const startSession = (id) => api.post(`/sessions/${id}/start`)
export const stopSession = (id) => api.post(`/sessions/${id}/stop`)
export const pauseSession = (id) => api.post(`/sessions/${id}/pause`)
export const resumeSession = (id) => api.post(`/sessions/${id}/resume`)
export const analyzeSession = (id) => api.post(`/sessions/${id}/analyze`)
export const deleteSession = (id) => api.delete(`/sessions/${id}`)

// Xuất dữ liệu thô của một phiên đo (22 cột). Timeout dài hơn mặc định vì tệp có thể lớn.
export const exportSessionCsv = (id) =>
  api.get(`/sessions/${id}/export/csv`, { responseType: 'blob', timeout: 60000 })

// Analysis & charts
export const getAnalysis = (id) => api.get(`/sessions/${id}/analysis`)
export const getChartTimeseries = (id, downsample = 2) => api.get(`/sessions/${id}/chart/timeseries`, { params: { downsample } })
export const getChartROM = (id) => api.get(`/sessions/${id}/chart/rom`)
export const getChartSymmetry = (id) => api.get(`/sessions/${id}/chart/symmetry`)
export const getChartGaitCycle = (id) => api.get(`/sessions/${id}/chart/gait-cycle`)
export const getChartPhase = (id) => api.get(`/sessions/${id}/chart/phase-distribution`)

// Self-service (user đo cho bản thân)
export const prepareSession     = (data) => api.post('/sessions/prepare', data)
export const prepareSessionSim  = ()     => api.post('/sessions/prepare-sim')
export const getMyActiveSession = ()     => api.get('/sessions/my-active')

// Serial
export const getSerialPorts  = () => api.get('/serial/ports')
export const autoDetectCH340 = () => api.get('/serial/auto-detect')
