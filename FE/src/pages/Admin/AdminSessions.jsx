import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Play, Square, Search, X, ChevronLeft, ChevronRight, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { getSessions, startSession, stopSession, deleteSession } from '../../api/sessions'
import { getUsers } from '../../api/auth'
import ConfirmDialog from '../../components/ui/ConfirmDialog'
import dayjs from 'dayjs'

const PAGE_SIZE = 20

function StatusBadge({ status }) {
  const map = {
    idle:      'bg-gray-100 text-gray-600',
    recording: 'bg-green-100 text-green-700',
    paused:    'bg-yellow-100 text-yellow-700',
    completed: 'bg-blue-100 text-blue-700',
  }
  const label = { idle: 'Chờ', recording: 'Đang đo', paused: 'Tạm dừng', completed: 'Hoàn thành' }
  return <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${map[status]}`}>{label[status]}</span>
}

export default function AdminSessions() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [confirmSession, setConfirmSession] = useState(null)

  const { data: uData } = useQuery({ queryKey: ['users'], queryFn: getUsers })
  const users   = uData?.data?.items ?? []
  const userMap = Object.fromEntries(users.map((u) => [u.id, u]))

  // Tìm user_id khớp với search để filter ở BE
  const matchedUserIds = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return null
    const ids = users
      .filter((u) =>
        u.full_name?.toLowerCase().includes(q) ||
        u.username?.toLowerCase().includes(q) ||
        u.email?.toLowerCase().includes(q)
      )
      .map((u) => u.id)
    return ids
  }, [users, search])

  // Khi search khớp đúng 1 user → truyền user_id lên BE để paginate đúng
  const filterUserId = matchedUserIds?.length === 1 ? matchedUserIds[0] : undefined

  const { data, isLoading } = useQuery({
    queryKey: ['admin-sessions', page, filterUserId],
    queryFn: () => getSessions({
      page,
      page_size: PAGE_SIZE,
      ...(filterUserId ? { user_id: filterUserId } : {}),
    }),
    keepPreviousData: true,
  })

  const total    = data?.data?.total ?? 0
  const sessions = data?.data?.items ?? []
  const totalPages = Math.ceil(total / PAGE_SIZE)

  // Nếu search khớp nhiều user → filter client-side
  const displayed = useMemo(() => {
    if (!matchedUserIds || matchedUserIds.length <= 1) return sessions
    return sessions.filter((s) => matchedUserIds.includes(s.user_id))
  }, [sessions, matchedUserIds])

  const handleSearch = (val) => {
    setSearch(val)
    setPage(1)
  }

  const startMut = useMutation({
    mutationFn: startSession,
    onSuccess: () => { toast.success('Bắt đầu thu dữ liệu'); qc.invalidateQueries(['admin-sessions']) },
    onError: (e) => toast.error(e.response?.data?.detail || 'Lỗi'),
  })

  const stopMut = useMutation({
    mutationFn: stopSession,
    onSuccess: () => { toast.success('Đã dừng'); qc.invalidateQueries(['admin-sessions']) },
  })

  const deleteMut = useMutation({
    mutationFn: deleteSession,
    onSuccess: () => { toast.success('Đã xóa phiên đo'); qc.invalidateQueries(['admin-sessions']) },
    onError: (e) => toast.error(e.response?.data?.detail || 'Không thể xóa phiên đo'),
    onSettled: () => setConfirmSession(null),
  })

  const askDelete = (s) => {
    if (s.status === 'recording') {
      toast.error('Không thể xóa phiên đang đo')
      return
    }
    setConfirmSession(s)
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-800">Lịch sử đo</h1>
        <p className="text-gray-500 mt-1">Tất cả phiên đo của người dùng trong hệ thống</p>
      </div>

      {/* Search + stats */}
      <div className="mb-4 flex items-center gap-3">
        <div className="relative w-80">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder="Tìm theo tên, username, email..."
            className="w-full pl-9 pr-9 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {search && (
            <button
              onClick={() => handleSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X size={14} />
            </button>
          )}
        </div>
        <span className="text-sm text-gray-500">
          Tổng <span className="font-semibold text-gray-700">{total}</span> phiên đo
        </span>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Người đo', 'Trạng thái', 'Số mẫu', 'Ghi chú', 'Thời gian', 'Thao tác'].map((h) => (
                <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading && (
              <tr><td colSpan={6} className="text-center py-10 text-gray-400">Đang tải...</td></tr>
            )}
            {!isLoading && displayed.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-10 text-gray-400">
                  {search ? 'Không tìm thấy kết quả phù hợp' : 'Chưa có phiên đo'}
                </td>
              </tr>
            )}
            {displayed.map((s) => {
              const u = userMap[s.user_id]
              return (
                <tr key={s.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm">
                    <p className="font-medium text-gray-800">{u?.full_name ?? '—'}</p>
                    <p className="text-xs text-gray-400">{u?.username ?? `#${s.user_id}`}</p>
                  </td>
                  <td className="px-6 py-4"><StatusBadge status={s.status} /></td>
                  <td className="px-6 py-4 text-gray-600">{s.reading_count ?? 0}</td>
                  <td className="px-6 py-4 text-gray-500 text-sm max-w-xs truncate">{s.notes || '—'}</td>
                  <td className="px-6 py-4 text-gray-500 text-sm">{dayjs(s.created_at).format('DD/MM/YYYY HH:mm')}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      {(s.status === 'idle' || s.status === 'paused') && (
                        <button onClick={() => startMut.mutate(s.id)}
                          className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg" title="Bắt đầu">
                          <Play size={16} />
                        </button>
                      )}
                      {s.status === 'recording' && (
                        <button onClick={() => stopMut.mutate(s.id)}
                          className="p-1.5 text-red-600 hover:bg-red-50 rounded-lg" title="Dừng">
                          <Square size={16} />
                        </button>
                      )}
                      <Link to={`/admin/sessions/${s.id}`} className="text-sm text-blue-600 hover:underline">Chi tiết</Link>
                      <button onClick={() => askDelete(s)}
                        disabled={s.status === 'recording' || deleteMut.isPending}
                        className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed"
                        title="Xóa phiên đo">
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100">
            <span className="text-sm text-gray-500">
              Trang {page} / {totalPages}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={16} />
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 1)
                .reduce((acc, p, idx, arr) => {
                  if (idx > 0 && p - arr[idx - 1] > 1) acc.push('...')
                  acc.push(p)
                  return acc
                }, [])
                .map((p, i) =>
                  p === '...'
                    ? <span key={`ellipsis-${i}`} className="px-2 text-gray-400 text-sm">...</span>
                    : <button
                        key={p}
                        onClick={() => setPage(p)}
                        className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors ${
                          p === page
                            ? 'bg-blue-600 text-white'
                            : 'text-gray-600 hover:bg-gray-100'
                        }`}
                      >
                        {p}
                      </button>
                )
              }
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmSession}
        title="Xóa phiên đo"
        message="Xóa phiên đo này? Hành động không thể hoàn tác."
        confirmText="Xóa"
        loading={deleteMut.isPending}
        onConfirm={() => confirmSession && deleteMut.mutate(confirmSession.id)}
        onCancel={() => setConfirmSession(null)}
      />
    </div>
  )
}
