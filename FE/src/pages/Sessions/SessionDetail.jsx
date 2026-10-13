import { useParams, Link, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Square, Pause, BarChart2, ArrowLeft, AlertTriangle, CheckCircle2, Clock, Download } from 'lucide-react'
import toast from 'react-hot-toast'
import { getSession, startSession, stopSession, pauseSession, resumeSession, analyzeSession } from '../../api/sessions'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useExportCsv } from '../../hooks/useExportCsv'
import RealtimeChart from '../../components/Charts/RealtimeChart'
import dayjs from 'dayjs'

function Badge({ status }) {
  const map = { idle: 'bg-gray-100 text-gray-600', recording: 'bg-green-100 text-green-700', paused: 'bg-yellow-100 text-yellow-700', completed: 'bg-blue-100 text-blue-700' }
  const label = { idle: 'Chờ', recording: 'Đang đo', paused: 'Tạm dừng', completed: 'Hoàn thành' }
  return <span className={`px-3 py-1 rounded-full text-sm font-medium ${map[status]}`}>{label[status]}</span>
}

function InfoCard({ label, value }) {
  return (
    <div className="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="font-semibold text-gray-800">{value ?? '—'}</p>
    </div>
  )
}

function ScoreBadge({ score }) {
  const s = Math.round(score ?? 0)
  const color = s >= 80 ? 'text-green-600 bg-green-50 border-green-200'
    : s >= 60 ? 'text-amber-600 bg-amber-50 border-amber-200'
    : 'text-red-600 bg-red-50 border-red-200'
  return (
    <div className={`flex flex-col items-center justify-center rounded-xl border p-4 ${color}`}>
      <span className="text-4xl font-bold">{s}</span>
      <span className="text-xs mt-1">/ 100</span>
      <span className="text-xs font-medium mt-1">Điểm dáng đi</span>
    </div>
  )
}

function SymmetryBar({ label, value }) {
  const v = Number(value ?? 0)
  const color = v < 10 ? '#10b981' : v < 25 ? '#f59e0b' : '#ef4444'
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="font-semibold" style={{ color }}>{v.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, v)}%`, backgroundColor: color }} />
      </div>
    </div>
  )
}

export default function SessionDetail() {
  const { id } = useParams()
  const { pathname } = useLocation()
  const isAdmin = pathname.startsWith('/admin')
  const backPath = isAdmin ? '/admin/sessions' : '/sessions'
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['session', id], queryFn: () => getSession(id), refetchInterval: (query) => query.state.data?.data?.status === 'recording' ? 3000 : false })
  const session = data?.data

  const { readings, status: wsStatus, clear } = useWebSocket(
    session?.status === 'recording' ? Number(id) : null
  )

  const { exportCsv, exportingId } = useExportCsv()

  const mutOpts = (msg) => ({
    onSuccess: () => { toast.success(msg); qc.invalidateQueries(['session', id]) },
    onError: (e) => toast.error(e.response?.data?.detail || 'Lỗi'),
  })

  const startMut   = useMutation({ mutationFn: () => startSession(id),   ...mutOpts('Bắt đầu thu dữ liệu') })
  const stopMut    = useMutation({ mutationFn: () => stopSession(id),    ...mutOpts('Đã dừng') })
  const pauseMut   = useMutation({ mutationFn: () => pauseSession(id),   ...mutOpts('Đã tạm dừng') })
  const resumeMut  = useMutation({ mutationFn: () => resumeSession(id),  ...mutOpts('Tiếp tục đo') })
  const analyzeMut = useMutation({ mutationFn: () => analyzeSession(id), ...mutOpts('Phân tích hoàn tất') })
  if (isLoading) return <div className="p-8 text-gray-400">Đang tải...</div>
  if (!session) return <div className="p-8 text-red-500">Không tìm thấy phiên đo</div>

  const analysis = session.analysis
  const hasData = (session.reading_count ?? 0) > 0
  const isCompleted = session.status === 'completed'
  const duration = session.start_time && session.end_time
    ? Math.round((new Date(session.end_time) - new Date(session.start_time)) / 1000)
    : null

  return (
    <div className="p-6 space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to={backPath} className="p-2 hover:bg-gray-100 rounded-lg"><ArrowLeft size={20} /></Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-gray-800 font-mono">{session.session_code}</h1>
            <Badge status={session.status} />
          </div>
          <p className="text-gray-400 text-sm mt-0.5">Tạo lúc {dayjs(session.created_at).format('DD/MM/YYYY HH:mm')}</p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-2">
        {(session.status === 'idle' || session.status === 'paused') && (
          <button onClick={() => startMut.mutate()} disabled={startMut.isPending}
            className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 text-sm">
            <Play size={15} /> Bắt đầu đo
          </button>
        )}
        {session.status === 'recording' && (
          <>
            <button onClick={() => pauseMut.mutate()} className="flex items-center gap-2 bg-yellow-500 text-white px-4 py-2 rounded-lg hover:bg-yellow-600 text-sm">
              <Pause size={15} /> Tạm dừng
            </button>
            <button onClick={() => stopMut.mutate()} className="flex items-center gap-2 bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 text-sm">
              <Square size={15} /> Dừng
            </button>
          </>
        )}
        {isCompleted && !analysis && hasData && (
          <button onClick={() => analyzeMut.mutate()} disabled={analyzeMut.isPending}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm">
            <BarChart2 size={15} /> {analyzeMut.isPending ? 'Đang phân tích...' : 'Phân tích'}
          </button>
        )}
        {analysis && (
          <Link to={isAdmin ? `/admin/analysis/${id}` : `/analysis/${id}`}
            className="flex items-center gap-2 bg-purple-600 text-white px-4 py-2 rounded-lg hover:bg-purple-700 text-sm">
            <BarChart2 size={15} /> Xem phân tích chi tiết
          </Link>
        )}
        {hasData && (
          <button onClick={() => exportCsv(session)} disabled={exportingId === session.id}
            className="flex items-center gap-2 bg-gray-100 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-200 text-sm disabled:opacity-50"
            title="Tải dữ liệu thô 22 cột của phiên đo này">
            <Download size={15} /> {exportingId === session.id ? 'Đang xuất...' : 'Xuất CSV'}
          </button>
        )}

      </div>

      {/* Info cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <InfoCard label="Cổng COM" value={session.com_port} />
        <InfoCard label="Số mẫu" value={session.reading_count ?? 0} />
        {duration != null
          ? <InfoCard label="Thời lượng" value={duration >= 60 ? `${Math.floor(duration / 60)}p ${duration % 60}s` : `${duration}s`} />
          : <InfoCard label="Bắt đầu" value={session.start_time ? dayjs(session.start_time).format('HH:mm:ss') : null} />
        }
        <InfoCard label={session.status === 'recording' ? 'Kết nối WS' : 'Kết thúc'} value={session.status === 'recording' ? wsStatus : (session.end_time ? dayjs(session.end_time).format('HH:mm DD/MM') : null)} />
      </div>

      {/* Notes */}
      {session.notes && (
        <div className="bg-gray-50 rounded-xl px-4 py-3 text-sm text-gray-600 border border-gray-100">
          <span className="font-medium text-gray-500 mr-2">Ghi chú:</span>{session.notes}
        </div>
      )}

      {/* ── Realtime chart when recording ── */}
      {session.status === 'recording' && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-800">Dữ liệu real-time ({readings.length} điểm)</h2>
            <button onClick={clear} className="text-sm text-gray-400 hover:text-gray-600">Xóa</button>
          </div>
          <RealtimeChart readings={readings} />
        </div>
      )}

      {/* ── Completed: no data, no analysis ── */}
      {isCompleted && !hasData && !analysis && (
        <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl p-5">
          <AlertTriangle size={18} className="text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium text-amber-800 text-sm">Không có dữ liệu</p>
            <p className="text-amber-700 text-sm mt-0.5">
              Phiên đo này không ghi lại mẫu nào. Hãy tạo phiên đo mới và dùng Giả lập hoặc cảm biến thật để thu dữ liệu.
            </p>
          </div>
        </div>
      )}

      {/* ── Completed + has data but no analysis ── */}
      {isCompleted && hasData && !analysis && (
        <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-xl p-5">
          <Clock size={18} className="text-blue-500 mt-0.5 shrink-0" />
          <div className="flex-1">
            <p className="font-medium text-blue-800 text-sm">Sẵn sàng phân tích</p>
            <p className="text-blue-700 text-sm mt-0.5">
              Đã thu được <strong>{session.reading_count} mẫu</strong>. Nhấn <strong>Phân tích</strong> để tính toán các chỉ số dáng đi.
            </p>
          </div>
          <button onClick={() => analyzeMut.mutate()} disabled={analyzeMut.isPending}
            className="shrink-0 flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm">
            <BarChart2 size={15} /> {analyzeMut.isPending ? 'Đang phân tích...' : 'Phân tích ngay'}
          </button>
        </div>
      )}

      {/* ── Analysis summary ── */}
      {analysis && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={18} className="text-green-500" />
            <h2 className="font-semibold text-gray-700">Kết quả phân tích</h2>
            <span className="text-xs text-gray-400 ml-auto">
              {dayjs(analysis.analyzed_at).format('HH:mm DD/MM/YYYY')}
            </span>
          </div>

          {/* 3 equal columns: Score | Symmetry | Gait cycle */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Score */}
            <ScoreBadge score={analysis.gait_score} />

            {/* Symmetry */}
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Chỉ số đối xứng</p>
              {[
                { label: 'Hông',    value: analysis.symmetry_index_hip },
                { label: 'Gối',     value: analysis.symmetry_index_knee },
              ].map(({ label, value }) => (
                <SymmetryBar key={label} label={label} value={value} />
              ))}
            </div>

            {/* Gait cycle */}
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Chu kỳ dáng đi</p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { label: 'Chu kỳ Trái',    value: analysis.left_gait_cycle?.count,                 unit: ' bước' },
                  { label: 'Nhịp Trái',       value: analysis.left_gait_cycle?.cadence_steps_per_min,  unit: '/phút' },
                  { label: 'Chu kỳ Phải',     value: analysis.right_gait_cycle?.count,                unit: ' bước' },
                  { label: 'Nhịp Phải',       value: analysis.right_gait_cycle?.cadence_steps_per_min, unit: '/phút' },
                ].map(({ label, value, unit }) => (
                  <div key={label} className="bg-gray-50 rounded-lg p-2.5 text-center">
                    <p className="text-[10px] text-gray-400 mb-0.5">{label}</p>
                    <p className="text-sm font-bold text-gray-800">
                      {value != null ? `${Number(value).toFixed(0)}${unit}` : '—'}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Remarks */}
          {analysis.remarks && (
            <div className="bg-gray-50 rounded-xl px-4 py-3 text-sm text-gray-600 border border-gray-100">
              <span className="font-medium text-gray-500 mr-2">Nhận xét:</span>{analysis.remarks}
            </div>
          )}

          <Link to={isAdmin ? `/admin/analysis/${id}` : `/analysis/${id}`}
            className="inline-flex items-center gap-2 text-sm text-purple-600 hover:text-purple-800 font-medium">
            <BarChart2 size={15} /> Xem đầy đủ biểu đồ và thống kê →
          </Link>
        </div>
      )}
    </div>
  )
}
