import api from './axios'

export const listCameras = (config = {}) => api.get('/camera/list', config)
export const scanCameras = (config = {}) => api.get('/camera/list', { ...config, params: { refresh: true } })
