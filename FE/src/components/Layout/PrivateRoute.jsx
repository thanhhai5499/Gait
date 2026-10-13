import { Navigate, Outlet } from 'react-router-dom'
import useAuthStore from '../../store/authStore'

export default function PrivateRoute({ adminOnly = false }) {
  const { token, user } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (adminOnly && user?.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}
