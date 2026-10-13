import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { Trash2, Download } from 'lucide-react'
import toast from 'react-hot-toast'
import { getSessions, deleteSession } from '../../api/sessions'
import { useExportCsv } from '../../hooks/useExportCsv'
import ConfirmDialog from '../../components/ui/ConfirmDialog'
import dayjs from 'dayjs'

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

export default function SessionList() {
  const { pathname } = useLocation()
  const isAdmin = pathname.startsWith('/admin')
  const qc = useQueryClient()
  // confirm = { type: 'one', session } | { type: 'empty' } | null
  const [confirm, setConfirm] = useState(null)
  const [bulkLoading, setBulkLoading] = useState(false)
  const { exportCsv, exportingId } = useExportCsv()
  const { data, isLoading } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions({ page_size: 50 }),
  })

  const sessions = data?.data?.items ?? []
  const emptySessions = sessions.filter(
    (s) => (s.reading_count ?? 0) === 0 && s.status !== 'recording'
  )

  const deleteMut = useMutation({
    mutationFn: deleteSession,
    onSuccess: () => { toast.success('Đã xóa phiên đo'); qc.invalidateQueries(['sessions']) },
    onError: (e) => toast.error(e.response?.data?.detail || 'Không thể xóa phiên đo'),
    onSettled: () => setConfirm(null),
  })

  const askDelete = (s) => {
    if (s.status === 'recording') {
      toast.error('Không thể xóa phiên đang đo')
      return
    }
    setConfirm({ type: 'one', session: s })
  }

  const handleDeleteEmpty = async () => {
    if (emptySessions.length === 0) return
    setBulkLoading(true)
    try {
      await Promise.all(emptySessions.map((s) => deleteSession(s.id)))
      toast.success(`Đã xóa ${emptySessions.length} phiên rỗng`)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Có lỗi khi xóa phiên rỗng')
    } finally {
      setBulkLoading(false)
      setConfirm(null)
      qc.invalidateQueries(['sessions'])
    }
  }

  const onConfirm = () => {
    if (confirm?.type === 'one') deleteMut.mutate(confirm.session.id)
    else if (confirm?.type === 'empty') handleDeleteEmpty()
  }

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Lịch sử đo</h1>
          <p className="text-gray-500 mt-1">Danh sách các phiên đo của bạn</p>
        </div>
        {emptySessions.length > 0 && (
          <button
            onClick={() => setConfirm({ type: 'empty' })}
            disabled={bulkLoading}
            className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            <Trash2 size={15} /> Xóa {emptySessions.length} phiên rỗng
          </button>
        )}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Trạng thái', 'Số mẫu', 'Thời gian', ''].map((h, i) => (
                <th key={i} className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading && (
              <tr><td colSpan={4} className="text-center py-10 text-gray-400">Đang tải...</td></tr>
            )}
            {!isLoading && sessions.length === 0 && (
              <tr><td colSpan={4} className="text-center py-10 text-gray-400">Chưa có phiên đo nào</td></tr>
            )}
            {sessions.map((s) => (
              <tr key={s.id} className="hover:bg-gray-50">
                <td className="px-6 py-4"><StatusBadge status={s.status} /></td>
                <td className="px-6 py-4 text-gray-600">{s.reading_count ?? 0}</td>
                <td className="px-6 py-4 text-gray-500 text-sm">{dayjs(s.created_at).format('DD/MM/YYYY HH:mm')}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-4">
                    <Link to={isAdmin ? `/admin/sessions/${s.id}` : `/sessions/${s.id}`} className="text-sm text-blue-600 hover:underline">
                      Chi tiết
                    </Link>
                    <button
                      onClick={() => exportCsv(s)}
                      disabled={(s.reading_count ?? 0) === 0 || exportingId === s.id}
                      className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed"
                      title={(s.reading_count ?? 0) === 0 ? 'Phiên chưa có dữ liệu để xuất' : 'Xuất dữ liệu thô (CSV)'}
                    >
                      <Download size={16} />
                    </button>
                    <button
                      onClick={() => askDelete(s)}
                      disabled={s.status === 'recording' || deleteMut.isPending}
                      className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed"
                      title="Xóa phiên đo"
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

      <ConfirmDialog
        open={!!confirm}
        title={confirm?.type === 'empty' ? 'Xóa phiên rỗng' : 'Xóa phiên đo'}
        message={
          confirm?.type === 'empty'
            ? `Xóa ${emptySessions.length} phiên đo rỗng (0 mẫu)? Hành động không thể hoàn tác.`
            : 'Xóa phiên đo này? Hành động không thể hoàn tác.'
        }
        confirmText="Xóa"
        loading={deleteMut.isPending || bulkLoading}
        onConfirm={onConfirm}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
