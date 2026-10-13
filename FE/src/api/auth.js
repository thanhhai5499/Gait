import api from './axios'

export const login = (username, password) => {
  const form = new URLSearchParams()
  form.append('username', username)
  form.append('password', password)
  return api.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    _skipRefresh: true,
  })
}

export const refreshTokenApi = (refreshToken) =>
  api.post('/auth/refresh', { refresh_token: refreshToken }, { _skipRefresh: true })

export const logoutApi = (refreshToken) =>
  api.post('/auth/logout', { refresh_token: refreshToken }, { _skipRefresh: true })

export const signup = (data) => api.post('/auth/signup', data)
export const getMe = () => api.get('/auth/me')
export const updateMyProfile = (data) => api.put('/auth/me/profile', data)
export const changePassword = (data) => api.put('/auth/me/password', data)
export const getUsers = () => api.get('/auth/users')
export const updateUser = (id, data) => api.put(`/auth/users/${id}`, data)
export const deleteUser = (id) => api.delete(`/auth/users/${id}`)
export const registerUser = (data) => api.post('/auth/register', data)
