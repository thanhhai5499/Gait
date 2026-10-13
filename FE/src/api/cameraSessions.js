import api from './axios'

export const saveCameraSession   = (data)   => api.post('/camera-sessions', data)
export const listCameraSessions  = (params) => api.get('/camera-sessions', { params })
export const getCameraSession    = (id)     => api.get(`/camera-sessions/${id}`)
export const deleteCameraSession = (id)     => api.delete(`/camera-sessions/${id}`)
