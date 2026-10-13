import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Gauge, ClipboardList, Activity, History,
  ShieldCheck, UserCog, LogOut, UserCircle, AlertCircle,
  KeyRound, Eye, EyeOff, X, Camera, Users,
} from 'lucide-react'
import toast from 'react-hot-toast'
import useAuthStore from '../../store/authStore'
import { logoutApi, changePassword } from '../../api/auth'
import clsx from 'clsx'

const USER_LINKS = [
  { to: '/',         icon: Gauge,       label: 'Đo lường',         end: true },
  { to: '/camera',   icon: Camera,      label: 'Đo bằng Camera' },
  { to: '/sessions', icon: History,     label: 'Lịch sử đo' },
  { to: '/profile',  icon: UserCircle,  label: 'Thông tin cá nhân' },
]

const ADMIN_LINKS = [
  { to: '/admin',          icon: ShieldCheck,   label: 'Tổng quan',    end: true },
  { to: '/admin/users',    icon: UserCog,        label: 'Người dùng' },
  { to: '/admin/sessions', icon: ClipboardList,  label: 'Lịch sử đo' },
  { to: '/admin/group-analysis', icon: Users,    label: 'Phân tích nhóm' },
]

function NavItem({ to, icon: Icon, label, end = false, warn = false }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors',
          isActive
            ? 'bg-blue-600 text-white'
            : 'text-gray-400 hover:bg-gray-800 hover:text-white'
        )
      }
    >
      <Icon size={18} />
      <span className="flex-1">{label}</span>
      {warn && <AlertCircle size={14} className="text-amber-400 shrink-0" />}
    </NavLink>
  )
}

function PasswordInput({ value, onChange, placeholder, name }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        name={name}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-blue-500"
        autoComplete="off"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
      >
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  )
}

function ChangePasswordModal({ onClose }) {
  const [form, setForm] = useState({ old_password: '', new_password: '', confirm: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleChange = (e) => {
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }))
    setError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (form.new_password.length < 6) {
      setError('Mật khẩu mới phải có ít nhất 6 ký tự.')
      return
    }
    if (form.new_password !== form.confirm) {
      setError('Mật khẩu xác nhận không khớp.')
      return
    }
    setLoading(true)
    try {
      await changePassword({ old_password: form.old_password, new_password: form.new_password })
      toast.success('Đổi mật khẩu thành công')
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'Đổi mật khẩu thất bại')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <KeyRound size={18} className="text-blue-600" />
            <h2 className="text-base font-semibold text-gray-800">Đổi mật khẩu</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium text-gray-700">Mật khẩu hiện tại</label>
            <PasswordInput
              name="old_password"
              value={form.old_password}
              onChange={handleChange}
              placeholder="Nhập mật khẩu hiện tại"
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium text-gray-700">Mật khẩu mới</label>
            <PasswordInput
              name="new_password"
              value={form.new_password}
              onChange={handleChange}
              placeholder="Ít nhất 6 ký tự"
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm font-medium text-gray-700">Xác nhận mật khẩu mới</label>
            <PasswordInput
              name="confirm"
              value={form.confirm}
              onChange={handleChange}
              placeholder="Nhập lại mật khẩu mới"
            />
          </div>

          {error && (
            <p className="text-xs text-red-500 flex items-center gap-1">
              <AlertCircle size={12} /> {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 text-sm rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {loading ? 'Đang lưu...' : 'Xác nhận'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Sidebar() {
  const { user, refreshToken, logout } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const [showChangePass, setShowChangePass] = useState(false)

  const handleLogout = async () => {
    if (refreshToken) {
      try { await logoutApi(refreshToken) } catch { /* server error không chặn logout client */ }
    }
    logout()
  }

  const profileIncomplete = !isAdmin && !user?.profile_complete
  const links = isAdmin ? ADMIN_LINKS : USER_LINKS

  return (
    <>
      <aside className="w-64 h-screen sticky top-0 bg-gray-900 text-white flex flex-col overflow-y-auto">
        {/* Logo */}
        <div className="p-6 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <Activity className="text-blue-400" size={28} />
            <div>
              <p className="font-bold text-lg leading-tight">Gait Analysis</p>
              <p className="text-xs text-gray-400">Phân tích dáng đi</p>
            </div>
          </div>
        </div>

        {/* Role label */}
        <div className={clsx(
          'mx-4 mt-4 px-3 py-1.5 rounded-lg text-xs font-semibold text-center',
          isAdmin ? 'bg-purple-900 text-purple-300' : 'bg-gray-800 text-gray-400'
        )}>
          {isAdmin ? '⚙ Quản trị viên' : '👤 Người dùng'}
        </div>

        {/* Nav */}
        <nav className="flex-1 p-4 space-y-1 mt-2">
          {links.map(({ to, icon, label, end }) => (
            <NavItem
              key={to}
              to={to}
              icon={icon}
              label={label}
              end={end}
              warn={to === '/profile' && profileIncomplete}
            />
          ))}
        </nav>

        {/* User info + logout */}
        <div className="p-4 border-t border-gray-700">
          {/* Click vào để đổi mật khẩu */}
          <button
            onClick={() => setShowChangePass(true)}
            className="flex items-center gap-3 w-full mb-3 rounded-lg px-2 py-1.5 hover:bg-gray-800 transition-colors text-left group"
            title="Đổi mật khẩu"
          >
            {user?.avatar_url
              ? <img src={user.avatar_url} alt="" className="w-8 h-8 rounded-full object-cover shrink-0" />
              : (
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-bold shrink-0">
                  {user?.full_name?.[0]?.toUpperCase()}
                </div>
              )
            }
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user?.full_name}</p>
              <p className="text-xs text-gray-400 truncate">{user?.email || user?.username}</p>
            </div>
            <KeyRound size={14} className="text-gray-600 group-hover:text-blue-400 shrink-0 transition-colors" />
          </button>

          <button
            onClick={handleLogout}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-400 hover:text-red-400 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <LogOut size={16} /> Đăng xuất
          </button>
        </div>
      </aside>

      {showChangePass && <ChangePasswordModal onClose={() => setShowChangePass(false)} />}
    </>
  )
}
