import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, Wifi, WifiOff, Radio, Play, Square, Settings, CheckCircle2, Loader2, AlertCircle } from 'lucide-react'
import { prepareSession, startSession, stopSession, getMyActiveSession, autoDetectCH340 } from '../api/sessions'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import useAuthStore from '../store/authStore'
import { useWebSocket } from '../hooks/useWebSocket'
import LegRealtimeChart from '../components/Charts/LegRealtimeChart'

/* ─── WS status indicator ───────────────────────────────────────── */

function WsIndicator({ status }) {
  const cfg = {
    connected:    { icon: Wifi,    color: 'text-green-500', label: 'Đã kết nối' },
    connecting:   { icon: Radio,   color: 'text-yellow-500 animate-pulse', label: 'Đang kết nối...' },
    disconnected: { icon: WifiOff, color: 'text-gray-400', label: 'Chưa kết nối' },
    error:        { icon: WifiOff, color: 'text-red-400', label: 'Lỗi kết nối' },
  }
  const { icon: Icon, color, label } = cfg[status] ?? cfg.disconnected
  return (
    <span className={`flex items-center gap-1 text-xs font-medium ${color}`}>
      <Icon size={13} />{label}
    </span>
  )
}

/* ─── joint metric card ─────────────────────────────────────────── */

function JointMetric({ label, value, min, max, rom, accentColor }) {
  const fmt = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}°`)
  return (
    <div className="bg-gray-50 rounded-xl p-3 border border-gray-100">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</span>
        <span className="text-lg font-bold" style={{ color: accentColor }}>{fmt(value)}</span>
      </div>
      <div className="grid grid-cols-3 gap-1 text-center">
        {[{ tag: 'Min', val: fmt(min) }, { tag: 'Max', val: fmt(max) }, { tag: 'ROM', val: fmt(rom) }].map(({ tag, val }) => (
          <div key={tag}>
            <p className="text-[10px] text-gray-400">{tag}</p>
            <p className="text-xs font-semibold text-gray-700">{val}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function ForceMetric({ label, value, min, max, accentColor }) {
  const fmt = (v) => (v == null ? '—' : `${Number(v).toFixed(1)} N`)
  return (
    <div className="bg-gray-50 rounded-xl p-3 border border-gray-100">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</span>
        <span className="text-lg font-bold" style={{ color: accentColor }}>{fmt(value)}</span>
      </div>
      <div className="grid grid-cols-2 gap-1 text-center">
        {[{ tag: 'Min', val: fmt(min) }, { tag: 'Max', val: fmt(max) }].map(({ tag, val }) => (
          <div key={tag}>
            <p className="text-[10px] text-gray-400">{tag}</p>
            <p className="text-xs font-semibold text-gray-700">{val}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── sensor metric card ────────────────────────────────────────── */

function SensorMetric({ label, value, unit, accentColor }) {
  const fmt = (v) => (v == null ? '—' : `${Number(v).toFixed(2)}`)
  return (
    <div className="bg-gray-50 rounded-xl p-3 border border-gray-100">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</span>
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-lg font-bold" style={{ color: accentColor }}>{fmt(value)}</span>
        <span className="text-xs text-gray-400">{unit}</span>
      </div>
    </div>
  )
}

/* ─── sensor metrics panel ──────────────────────────────────────── */

function SensorMetricsPanel({ readings }) {
  const latest = readings[readings.length - 1] ?? {}
  return (
    <div className="bg-white rounded-2xl border-2 border-indigo-200 shadow-sm flex flex-col">
      <div className="bg-indigo-50 rounded-t-2xl px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-indigo-500" />
          <h2 className="font-bold text-sm text-indigo-700">Cảm biến IMU & Chất lượng</h2>
        </div>
        {latest.signal_quality != null && (
          <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 text-green-700">
            Tín hiệu: {latest.signal_quality}%
          </span>
        )}
      </div>
      <div className="p-4 flex flex-col gap-3 flex-1">
        <div>
          <p className="text-xs font-semibold text-gray-600 mb-2">Gia tốc (m/s²)</p>
          <div className="grid grid-cols-3 gap-2">
            <SensorMetric label="X" value={latest.accel_x} unit="m/s²" accentColor="#6366f1" />
            <SensorMetric label="Y" value={latest.accel_y} unit="m/s²" accentColor="#8b5cf6" />
            <SensorMetric label="Z" value={latest.accel_z} unit="m/s²" accentColor="#a855f7" />
          </div>
        </div>
        <div>
          <p className="text-xs font-semibold text-gray-600 mb-2">Con quay hồi chuyển (deg/s)</p>
          <div className="grid grid-cols-3 gap-2">
            <SensorMetric label="X" value={latest.gyro_x} unit="deg/s" accentColor="#06b6d4" />
            <SensorMetric label="Y" value={latest.gyro_y} unit="deg/s" accentColor="#0891b2" />
            <SensorMetric label="Z" value={latest.gyro_z} unit="deg/s" accentColor="#0e7490" />
          </div>
        </div>
        <div>
          <p className="text-xs font-semibold text-gray-600 mb-2">Từ trường (μT)</p>
          <div className="grid grid-cols-3 gap-2">
            <SensorMetric label="X" value={latest.magn_x} unit="μT" accentColor="#f59e0b" />
            <SensorMetric label="Y" value={latest.magn_y} unit="μT" accentColor="#d97706" />
            <SensorMetric label="Z" value={latest.magn_z} unit="μT" accentColor="#b45309" />
          </div>
        </div>
      </div>
    </div>
  )
}

/* ─── leg panel ─────────────────────────────────────────────────── */

const LEG_KEYS = {
  left:  { hip: 'left_hip',  knee: 'left_knee',  toe: 'left_force_1',  heel: 'left_force_2',  phase: 'phase_left' },
  right: { hip: 'right_hip', knee: 'right_knee', toe: 'right_force_1', heel: 'right_force_2', phase: 'phase_right' },
}

const PHASE_LABELS = {
  stance:  { label: 'Đứng tựa (Stance)', color: 'bg-blue-100 text-blue-700' },
  swing:   { label: 'Xoay chân (Swing)', color: 'bg-purple-100 text-purple-700' },
  unknown: { label: 'Không xác định',    color: 'bg-gray-100 text-gray-500' },
}

function computeStats(readings, key) {
  const vals = readings.map((r) => r[key]).filter((v) => v != null && !isNaN(v))
  if (!vals.length) return { current: null, min: null, max: null, rom: null }
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  return { current: readings[readings.length - 1]?.[key] ?? null, min, max, rom: max - min }
}

function LegPanel({ side, readings }) {
  const keys = LEG_KEYS[side]
  const isLeft = side === 'left'

  const stats = useMemo(() => ({
    hip:   computeStats(readings, keys.hip),
    knee:  computeStats(readings, keys.knee),
    toe:   computeStats(readings, keys.toe),
    heel:  computeStats(readings, keys.heel),
    phase: readings[readings.length - 1]?.[keys.phase] ?? null,
  }), [readings, keys])

  const phaseInfo   = PHASE_LABELS[stats.phase] ?? PHASE_LABELS.unknown
  const borderColor = isLeft ? 'border-blue-200'  : 'border-rose-200'
  const headerBg    = isLeft ? 'bg-blue-50'        : 'bg-rose-50'
  const titleColor  = isLeft ? 'text-blue-700'     : 'text-rose-700'
  const dotColor    = isLeft ? 'bg-blue-500'       : 'bg-rose-500'

  return (
    <div className={`bg-white rounded-2xl border-2 ${borderColor} shadow-sm flex flex-col`}>
      <div className={`${headerBg} rounded-t-2xl px-5 py-3 flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${dotColor}`} />
          <h2 className={`font-bold text-sm ${titleColor}`}>{isLeft ? 'Chân Trái' : 'Chân Phải'}</h2>
        </div>
        {stats.phase && (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${phaseInfo.color}`}>
            {phaseInfo.label}
          </span>
        )}
      </div>
      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="grid grid-cols-4 gap-2">
          <JointMetric label="Hông"      value={stats.hip.current}  min={stats.hip.min}  max={stats.hip.max}  rom={stats.hip.rom}  accentColor="#6b7280" />
          <JointMetric label="Gối"       value={stats.knee.current} min={stats.knee.min} max={stats.knee.max} rom={stats.knee.rom} accentColor="#ef4444" />
          <ForceMetric label="Mũi chân"  value={stats.toe.current}  min={stats.toe.min}  max={stats.toe.max}  accentColor="#f59e0b" />
          <ForceMetric label="Gót chân"  value={stats.heel.current} min={stats.heel.min} max={stats.heel.max} accentColor="#ea580c" />
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">
            Góc khớp theo thời gian
            {readings.length > 0 && <span className="ml-1 text-gray-300">({readings.length} điểm)</span>}
          </p>
          <LegRealtimeChart readings={readings} side={side} />
        </div>
      </div>
    </div>
  )
}

/* ─── control bar ────────────────────────────────────────────────── */
/*  3 trạng thái: idle | previewing | recording                      */

const AUTO_STOP_MS = 90_000  // tự động dừng đo sau 1 phút 30 giây

function ControlBar({ prepSession, activeSession, readings, wsStatus, onPrepared, onStartRecording, onCancelPrepare, onStopped, profileComplete }) {
  const qc = useQueryClient()

  /* — idle: nút Kết nối — */
  const connectMut = useMutation({
    mutationFn: async () => {
      const detectRes  = await autoDetectCH340()
      const prepareRes = await prepareSession({ com_port: detectRes.data.port, baud_rate: 115200 })
      return { port: detectRes.data.port, session: prepareRes.data }
    },
    onSuccess: ({ port, session }) => { toast.success(`Đã kết nối CH340 tại ${port}`); onPrepared(session) },
    onError:   (e) => toast.error(e.response?.data?.detail || 'Không thể kết nối thiết bị CH340'),
  })

/* — previewing: nút Bắt đầu ghi — */
  const startMut = useMutation({
    mutationFn: () => startSession(prepSession.id),
    onSuccess:  () => { toast.success('Bắt đầu ghi dữ liệu!'); onStartRecording() },
    onError:    (e) => toast.error(e.response?.data?.detail || 'Lỗi khi bắt đầu ghi'),
  })

  /* — recording: nút Dừng đo — */
  const stopMut = useMutation({
    mutationFn: () => stopSession(activeSession.id),
    onSuccess:  () => {
      toast.success('Đã dừng đo')
      qc.invalidateQueries(['sessions'])
      qc.invalidateQueries(['my-active'])
      onStopped()
    },
    onError: () => toast.error('Lỗi khi dừng'),
  })

  /* — recording: tự động dừng sau AUTO_STOP_MS kể từ start_time — */
  useEffect(() => {
    if (!activeSession?.start_time) return
    const startMs = new Date(activeSession.start_time).getTime()
    const remainingMs = startMs + AUTO_STOP_MS - Date.now()
    const timer = setTimeout(() => stopMut.mutate(), Math.max(remainingMs, 0))
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession?.id, activeSession?.start_time])

  /* ── recording state ── */
  if (activeSession) {
    const elapsed = activeSession.start_time
      ? Math.floor((Date.now() - new Date(activeSession.start_time).getTime()) / 1000)
      : 0
    const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
    const ss = String(elapsed % 60).padStart(2, '0')

    return (
      <div className="bg-white rounded-2xl border-2 border-green-200 shadow-sm px-5 py-3">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
            <span className="font-semibold text-green-700 text-sm">Đang thu dữ liệu</span>
          </div>
          <span className="text-xs font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
            {activeSession.session_code}
          </span>
          <WsIndicator status={wsStatus} />

          <div className="flex items-center gap-4 ml-auto">
            <div className="text-center">
              <p className="text-[10px] text-gray-400">Số mẫu</p>
              <p className="text-sm font-semibold text-gray-700">{activeSession.reading_count ?? 0}</p>
            </div>
            <div className="text-center">
              <p className="text-[10px] text-gray-400">Thời gian</p>
              <p className="text-sm font-semibold font-mono text-gray-700">{mm}:{ss}</p>
            </div>
            <button
              onClick={() => stopMut.mutate()}
              disabled={stopMut.isPending}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg font-semibold text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              <Square size={14} />
              {stopMut.isPending ? 'Đang dừng...' : 'Dừng đo'}
            </button>
            <Link
              to={`/sessions/${activeSession.id}`}
              className="px-3 py-1.5 rounded-lg text-sm text-gray-600 border border-gray-200 hover:bg-gray-50"
            >
              Chi tiết
            </Link>
          </div>
        </div>
      </div>
    )
  }

  /* ── previewing state ── */
  if (prepSession) {
    const isStable = readings.length >= 10
    return (
      <div className="bg-white rounded-2xl border-2 border-blue-200 shadow-sm px-5 py-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse" />
            <span className="font-semibold text-blue-700 text-sm">Đang theo dõi tín hiệu</span>
          </div>
          <span className="text-xs font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
            {prepSession.session_code}
          </span>
          <WsIndicator status={wsStatus} />

          <div className="flex items-center gap-2 ml-auto">
            {isStable ? (
              <span className="flex items-center gap-1 text-xs text-green-600 font-medium">
                <CheckCircle2 size={13} /> Tín hiệu ổn định
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-amber-500 font-medium">
                <Loader2 size={13} className="animate-spin" /> Chờ tín hiệu... ({readings.length}/10)
              </span>
            )}
            <button
              onClick={() => startMut.mutate()}
              disabled={!isStable || startMut.isPending}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg font-semibold text-sm bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {startMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Bắt đầu ghi
            </button>
            <button
              onClick={onCancelPrepare}
              disabled={startMut.isPending}
              className="px-3 py-1.5 rounded-lg text-sm text-gray-500 border border-gray-200 hover:bg-gray-50 transition-colors"
            >
              Huỷ
            </button>
          </div>
        </div>
      </div>
    )
  }

  /* ── idle state ── */
  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm px-5 py-3">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 shrink-0">
          <div className="w-7 h-7 bg-blue-100 rounded-lg flex items-center justify-center">
            <Settings size={14} className="text-blue-600" />
          </div>
          <span className="text-sm font-semibold text-gray-700">Chuẩn bị đo</span>
        </div>
        {!profileComplete && (
          <span className="flex items-center gap-1 text-xs text-amber-600 font-medium">
            <AlertCircle size={13} />
            Cần cập nhật thông tin cá nhân
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => connectMut.mutate()}
          disabled={connectMut.isPending || !profileComplete}
          title={!profileComplete ? 'Vui lòng cập nhật thông tin cá nhân trước khi đo' : undefined}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg font-semibold text-sm bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {connectMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Activity size={14} />}
          {connectMut.isPending ? 'Đang kết nối...' : 'Kết nối'}
        </button>
      </div>
    </div>
  )
}

/* ─── main dashboard ─────────────────────────────────────────────── */

export default function Dashboard() {
  const { user } = useAuthStore()
  const profileComplete = user?.profile_complete ?? false
  const qc = useQueryClient()
  const [prepSession, setPrepSession] = useState(null)

  const { data: activeData } = useQuery({
    queryKey: ['my-active'],
    queryFn: getMyActiveSession,
  })

  const activeSession = activeData?.data ?? null
  const wsSessionId   = prepSession?.id ?? (activeSession?.status === 'recording' ? activeSession.id : null)
  const { readings, status: wsStatus } = useWebSocket(wsSessionId)

  const handleStartRecording = () => {
    setPrepSession(null)
    qc.invalidateQueries(['my-active'])
    qc.invalidateQueries(['sessions'])
  }

  const handleCancelPrepare = async () => {
    if (prepSession) {
      try { await stopSession(prepSession.id) } catch (_) { /* ignore */ }
    }
    setPrepSession(null)
  }

  const handleStopped = () => {
    setPrepSession(null)
    qc.invalidateQueries(['my-active'])
    qc.invalidateQueries(['sessions'])
  }

  return (
    <div className="p-6 space-y-5">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold text-gray-800">Xin chào, {user?.full_name}</h1>
        <p className="text-gray-500 mt-0.5 text-sm">Theo dõi dáng đi realtime</p>
      </div>

      {/* Profile incomplete banner */}
      {!profileComplete && (
        <div className="flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
          <AlertCircle size={16} className="shrink-0" />
          <span>
            Thông tin cá nhân chưa đầy đủ —{' '}
            <Link to="/profile" className="font-semibold underline hover:text-amber-900">
              cập nhật ngay
            </Link>{' '}
            để sử dụng tính năng.
          </span>
        </div>
      )}

      {/* Control bar — thay đổi trạng thái */}
      <ControlBar
        prepSession={prepSession}
        activeSession={activeSession}
        readings={readings}
        wsStatus={wsStatus}
        profileComplete={profileComplete}
        onPrepared={(s) => setPrepSession(s)}
        onStartRecording={handleStartRecording}
        onCancelPrepare={handleCancelPrepare}
        onStopped={handleStopped}
      />

      {/* Realtime panels — luôn hiển thị */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <LegPanel side="left"  readings={readings} />
        <LegPanel side="right" readings={readings} />
      </div>
      <SensorMetricsPanel readings={readings} />
    </div>
  )
}
