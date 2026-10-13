import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import queryClient from '../api/queryClient'

const useAuthStore = create(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      user: null,

      setAuth: (token, refreshToken, user) => {
        queryClient.clear()
        set({ token, refreshToken, user })
      },

      setTokens: (token, refreshToken) => {
        set({ token, refreshToken })
      },

      setUser: (user) => set({ user }),

      logout: () => {
        queryClient.clear()
        set({ token: null, refreshToken: null, user: null })
      },

      isAdmin: () => {
        const state = useAuthStore.getState()
        return state.user?.role === 'admin'
      },
    }),
    {
      name: 'gait-auth',
      partialize: (s) => ({ token: s.token, refreshToken: s.refreshToken, user: s.user }),
    }
  )
)

export default useAuthStore
