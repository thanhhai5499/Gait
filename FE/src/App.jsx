import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import queryClient from './api/queryClient'

import AppLayout from './components/Layout/AppLayout'
import PrivateRoute from './components/Layout/PrivateRoute'

import Login from './pages/Login'
import Signup from './pages/Signup'

// User pages
import Dashboard from './pages/Dashboard'
import CameraAnalysis from './pages/Camera/CameraAnalysis'
import SessionList from './pages/Sessions/SessionList'
import SessionDetail from './pages/Sessions/SessionDetail'
import AnalysisDetail from './pages/Analysis/AnalysisDetail'
import Profile from './pages/Profile'

// Admin pages
import AdminDashboard from './pages/Admin/AdminDashboard'
import UserManagement from './pages/Admin/UserManagement'
import AdminSessions from './pages/Admin/AdminSessions'
import GroupAnalysis from './pages/Admin/GroupAnalysis'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* ── User routes ──────────────────────────────── */}
          <Route element={<PrivateRoute />}>
            <Route element={<AppLayout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/sessions" element={<SessionList />} />
              <Route path="/sessions/:id" element={<SessionDetail />} />
              <Route path="/analysis/:id" element={<AnalysisDetail />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/camera" element={<CameraAnalysis />} />
            </Route>
          </Route>

          {/* ── Admin routes (admin only) ─────────────────── */}
          <Route element={<PrivateRoute adminOnly />}>
            <Route element={<AppLayout />}>
              <Route path="/admin" element={<AdminDashboard />} />
              <Route path="/admin/users" element={<UserManagement />} />
              <Route path="/admin/sessions" element={<AdminSessions />} />
              <Route path="/admin/sessions/:id" element={<SessionDetail />} />
              <Route path="/admin/analysis/:id" element={<AnalysisDetail />} />
              <Route path="/admin/group-analysis" element={<GroupAnalysis />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" toastOptions={{ duration: 3000 }} />
    </QueryClientProvider>
  )
}
