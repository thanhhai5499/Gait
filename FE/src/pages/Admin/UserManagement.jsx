import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Shield, User, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { getUsers, registerUser, updateUser, deleteUser } from '../../api/auth'
import dayjs from 'dayjs'

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

const INIT_FORM = { username: '', email: '', full_name: '', password: '', role: 'user' }

export default function UserManagement() {
  const qc = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState(INIT_FORM)
  const [confirmDelete, setConfirmDelete] = useState(null)

  const { data, isLoading } = useQuery({ queryKey: ['users'], queryFn: getUsers })
  const users = data?.data?.items ?? []

  const createMut = useMutation({
    mutationFn: registerUser,
    onSuccess: () => { toast.success('Đã tạo tài khoản'); qc.invalidateQueries(['users']); setShowModal(false); setForm(INIT_FORM) },
    onError: (e) => toast.error(e.response?.data?.detail || 'Tạo thất bại'),
  })

  const roleMut = useMutation({
    mutationFn: ({ id, role }) => updateUser(id, { role }),
    onSuccess: () => { toast.success('Đã cập nhật vai trò'); qc.invalidateQueries(['users']) },
    onError: () => toast.error('Cập nhật thất bại'),
  })

  const deleteMut = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => { toast.success('Đã xóa tài khoản'); qc.invalidateQueries(['users']); setConfirmDelete(null) },
    onError: (e) => toast.error(e.response?.data?.detail || 'Xóa thất bại'),
  })

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Quản lý tài khoản</h1>
          <p className="text-gray-500 mt-1">Tạo và quản lý người dùng hệ thống</p>
        </div>
        <button onClick={() => setShowModal(true)}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors">
          <Plus size={18} /> Tạo tài khoản
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Người dùng', 'Username', 'Vai trò', 'Đăng nhập', 'Ngày tạo', 'Thao tác'].map((h) => (
                <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading && <tr><td colSpan={6} className="text-center py-10 text-gray-400">Đang tải...</td></tr>}
            {!isLoading && users.length === 0 && (
              <tr><td colSpan={6} className="text-center py-10 text-gray-400">Không có tài khoản</td></tr>
            )}
            {users.map((u) => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    {u.avatar_url
                      ? <img src={u.avatar_url} alt="" className="w-8 h-8 rounded-full object-cover" />
                      : <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center"><User size={16} className="text-blue-600" /></div>
                    }
                    <div>
                      <p className="font-medium text-gray-800">{u.full_name}</p>
                      <p className="text-xs text-gray-400">{u.email || '—'}</p>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 font-mono text-gray-600 text-sm">{u.username}</td>
                <td className="px-6 py-4"><RoleBadge role={u.role} /></td>
                <td className="px-6 py-4"><AuthBadge provider={u.auth_provider} /></td>
                <td className="px-6 py-4 text-gray-500 text-sm">{dayjs(u.created_at).format('DD/MM/YYYY')}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => roleMut.mutate({ id: u.id, role: u.role === 'admin' ? 'user' : 'admin' })}
                      disabled={roleMut.isPending}
                      className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-500 hover:text-purple-600"
                      title={u.role === 'admin' ? 'Hạ xuống User' : 'Nâng lên Admin'}
                    >
                      {u.role === 'admin' ? <User size={16} /> : <Shield size={16} />}
                    </button>
                    <button
                      onClick={() => setConfirmDelete(u)}
                      className="p-1.5 hover:bg-red-50 rounded-lg text-gray-400 hover:text-red-600"
                      title="Xóa tài khoản"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-md p-6">
            <h3 className="text-lg font-semibold mb-4">Tạo tài khoản mới</h3>
            <div className="space-y-3">
              <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                placeholder="Họ và tên *" className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="Username *" className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="Email" className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="Mật khẩu *" className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={() => { setShowModal(false); setForm(INIT_FORM) }}
                className="flex-1 border border-gray-300 py-2.5 rounded-lg hover:bg-gray-50">Hủy</button>
              <button
                onClick={() => createMut.mutate(form)}
                disabled={!form.full_name || !form.username || !form.password || createMut.isPending}
                className="flex-1 bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-60">
                {createMut.isPending ? 'Đang tạo...' : 'Tạo'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-2">Xác nhận xóa</h3>
            <p className="text-gray-600 mb-5">
              Xóa tài khoản <strong>{confirmDelete.full_name}</strong> ({confirmDelete.username})? Hành động này không thể hoàn tác.
            </p>
            <div className="flex gap-3">
              <button onClick={() => setConfirmDelete(null)} className="flex-1 border border-gray-300 py-2.5 rounded-lg hover:bg-gray-50">Hủy</button>
              <button onClick={() => deleteMut.mutate(confirmDelete.id)} disabled={deleteMut.isPending}
                className="flex-1 bg-red-600 text-white py-2.5 rounded-lg hover:bg-red-700 disabled:opacity-60">
                {deleteMut.isPending ? 'Đang xóa...' : 'Xóa'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
