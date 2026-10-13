import { useQuery } from '@tanstack/react-query'
import { Users, ClipboardList, Activity, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getSessions } from '../../api/sessions'
import { getUsers } from '../../api/auth'
import dayjs from 'dayjs'

function StatCard({ icon: Icon, label, value, color, to }) {
  const inner = (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-3xl font-bold text-gray-800 mt-1">{value ?? '—'}</p>
      </div>
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color}`}>
        <Icon size={24} className="text-white" />
      </div>
    </div>
  )
  return to
    ? <Link to={to} className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">{inner}</Link>
    : <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">{inner}</div>
}

function RoleBadge({ role }) {
  return role === 'admin'
    ? <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">Admin</span>
    : <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">User</span>
}

function AuthBadge({ provider }) {
  return provider === 'google'
    ? <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-600">Google</span>
    : <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500">Local</span>
}

export default function AdminDashboard() {
  const { data: uData } = useQuery({ queryKey: ['users'], queryFn: getUsers })
  const { data: sData } = useQuery({ queryKey: ['sessions'], queryFn: () => getSessions({ page_size: 1 }) })
  const { data: recData } = useQuery({ queryKey: ['sessions-recording'], queryFn: () => getSessions({ status: 'recording', page_size: 10 }) })

  const users = uData?.data?.items ?? []
  const totalUsers = uData?.data?.total ?? 0
  const totalSessions = sData?.data?.total ?? 0
  const recording = recData?.data?.total ?? 0

  return (
    <div className="p-8">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <ShieldCheck size={28} className="text-purple-600" />
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Tổng quan</h1>
            <p className="text-gray-500 mt-0.5">Quản trị và giám sát hệ thống</p>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 mb-8">
        <StatCard icon={Users}         label="Tài khoản"        value={totalUsers}    color="bg-purple-500" to="/admin/users" />
        <StatCard icon={ClipboardList} label="Phiên đo"         value={totalSessions} color="bg-indigo-500" to="/admin/sessions" />
        <StatCard icon={Activity}      label="Đang thu dữ liệu" value={recording}     color="bg-green-500" />
      </div>

      {/* User list */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">Danh sách tài khoản ({totalUsers})</h2>
          <Link to="/admin/users" className="text-sm text-purple-600 hover:underline">Quản lý →</Link>
        </div>
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Họ tên', 'Username', 'Vai trò', 'Đăng nhập qua', 'Ngày tạo'].map((h) => (
                <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {users.length === 0 && (
              <tr><td colSpan={5} className="text-center py-8 text-gray-400">Chưa có tài khoản</td></tr>
            )}
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-6 py-3 font-medium text-gray-800">{u.full_name}</td>
                <td className="px-6 py-3 font-mono text-sm text-gray-600">{u.username}</td>
                <td className="px-6 py-3"><RoleBadge role={u.role} /></td>
                <td className="px-6 py-3"><AuthBadge provider={u.auth_provider} /></td>
                <td className="px-6 py-3 text-gray-500 text-sm">{dayjs(u.created_at).format('DD/MM/YYYY')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
