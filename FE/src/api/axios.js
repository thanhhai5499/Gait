import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// Đọc access token từ zustand persist store
const getAccessToken = () => {
  try {
    const stored = JSON.parse(localStorage.getItem('gait-auth') || '{}')
    return stored?.state?.token ?? null
  } catch {
    return null
  }
}

const getRefreshToken = () => {
  try {
    const stored = JSON.parse(localStorage.getItem('gait-auth') || '{}')
    return stored?.state?.refreshToken ?? null
  } catch {
    return null
  }
}

// Gắn access token vào mọi request
api.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Xử lý 401 — thử refresh token trước khi logout
let isRefreshing = false
let pendingQueue = []

const processQueue = (error, token = null) => {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  pendingQueue = []
}

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config

    // Bỏ qua nếu request này đã được đánh dấu skip (refresh/logout endpoint)
    if (original._skipRefresh) {
      return Promise.reject(err)
    }

    if (err.response?.status === 401 && !original._retried) {
      original._retried = true

      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        // Không có refresh token → không phải session hết hạn, trả lỗi gốc về caller
        return Promise.reject(err)
      }

      if (isRefreshing) {
        // Xếp hàng chờ token mới
        return new Promise((resolve, reject) => {
          pendingQueue.push({ resolve, reject })
        }).then((newToken) => {
          original.headers.Authorization = `Bearer ${newToken}`
          return api(original)
        })
      }

      isRefreshing = true
      try {
        const { default: useAuthStore } = await import('../store/authStore')
        // Gọi thẳng fetch để tránh interceptor vòng lặp
        const res = await axios.post(
          '/api/auth/refresh',
          { refresh_token: refreshToken },
          { timeout: 10000 }
        )
        const { access_token, refresh_token: new_refresh, user } = res.data
        useAuthStore.getState().setAuth(access_token, new_refresh, user)
        processQueue(null, access_token)
        original.headers.Authorization = `Bearer ${access_token}`
        return api(original)
      } catch (refreshErr) {
        processQueue(refreshErr, null)
        return _forceLogout()
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(err)
  }
)

async function _forceLogout() {
  const { default: useAuthStore } = await import('../store/authStore')
  useAuthStore.getState().logout()
  window.location.href = '/login'
  return Promise.reject(new Error('Session expired'))
}

export default api
