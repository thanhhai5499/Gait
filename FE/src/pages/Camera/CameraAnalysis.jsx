import { useState, useEffect, useRef, useCallback, Fragment } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Camera, CameraOff, Video, RefreshCw, Activity,
  Play, Pause, BarChart2, RotateCcw, ScanLine,
  Layers, Wifi, WifiOff, Circle, ChevronDown, Check,
  Save, History, FlaskConical, Trash2,
} from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, BarChart, Bar, Cell,
} from 'recharts'
import toast from 'react-hot-toast'
import dayjs from 'dayjs'
import useAuthStore from '../../store/authStore'
import { listCameras, scanCameras } from '../../api/camera'
import { getSessions } from '../../api/sessions'
import { saveCameraSession, listCameraSessions, deleteCameraSession } from '../../api/cameraSessions'
import { useFusionBuffer } from '../../hooks/useFusionBuffer'

const MAX_HISTORY  = 300
const RECORD_LIMIT = 6000
const RECORD_FPS       = 30
const AUTO_STOP_FRAMES = RECORD_FPS * 90  // tự động dừng ghi sau 1 phút 30 giây

// ── WS URL ────────────────────────────────────────────────────────────────────
function buildWsUrl(cameraId, token, role) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const path  = cameraId === 'realsense' ? '/ws/realsense' : `/ws/camera/${cameraId}`
  const base  = `${proto}://${window.location.host}${path}`
  const params = new URLSearchParams()
  if (token) params.set('token', token)
  if (role && role !== 'lateral') params.set('role', role)
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

// ── Clinical-grade analysis helpers ───────────────────────────────────────────

function median(arr) {
  if (!arr.length) return null
  const sorted = [...arr].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function percentile(sortedArr, pct) {
  if (!sortedArr.length) return null
  const idx = (pct / 100) * (sortedArr.length - 1)
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi) return sortedArr[lo]
  return sortedArr[lo] + (sortedArr[hi] - sortedArr[lo]) * (idx - lo)
}

function medianFilter(arr, windowSize = 5) {
  const half = Math.floor(windowSize / 2)
  const result = new Array(arr.length)
  for (let i = 0; i < arr.length; i++) {
    const start = Math.max(0, i - half)
    const end = Math.min(arr.length, i + half + 1)
    const window = arr.slice(start, end).sort((a, b) => a - b)
    result[i] = window[Math.floor(window.length / 2)]
  }
  return result
}

function removeOutliers(values, lowerPct = 2.5, upperPct = 97.5) {
  if (values.length < 10) return values
  const sorted = [...values].sort((a, b) => a - b)
  const lo = sorted[Math.floor(sorted.length * lowerPct / 100)]
  const hi = sorted[Math.ceil(sorted.length * upperPct / 100) - 1]
  return values.filter(v => v >= lo && v <= hi)
}

function filterByConfidence(data, minConfidence = 0.3, minCameras = 1) {
  return data.filter(frame => {
    if (frame.cameras_active != null && frame.cameras_active < minCameras) return false
    const conf = frame.confidence
    if (!conf) return true // legacy frames without confidence metadata
    const scores = [conf.lateral, conf.frontal, conf.posterior].filter(v => v != null && v > 0)
    if (!scores.length) return true
    const avgConf = scores.reduce((s, v) => s + v, 0) / scores.length
    return avgConf >= minConfidence
  })
}

function normalizePelvicObliquity(value) {
  if (value == null) return null
  // Backend: arccos(dot(pelvis_unit, [1,0])) → 0°=level OR 180°=level
  // Normalize to: 0° = level pelvis, positive = tilt
  if (value > 90) return Math.abs(180 - value)
  return value
}

function computeJointStats(values) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const p5  = percentile(sorted, 5)
  const p50 = percentile(sorted, 50)
  const p95 = percentile(sorted, 95)
  const avg = values.reduce((s, v) => s + v, 0) / values.length
  return {
    mean:   +avg.toFixed(1),
    min:    +p5.toFixed(1),    // P5 — functional minimum
    max:    +p95.toFixed(1),   // P95 — functional maximum
    rom:    +(p95 - p5).toFixed(1),
    median: +p50.toFixed(1),
  }
}

function computeCadenceFromBackendData(frames) {
  // Backend GaitCycleDetector streams cadence in real-time via WS
  const cadenceValues = frames
    .map(f => f.cadence ?? f.fused?.cadence)
    .filter(v => v != null && v >= 40 && v <= 180) // physiological range
  if (cadenceValues.length >= 10) {
    return median(cadenceValues)
  }
  return null
}

function detectStepsFromKneeAngles(kneeAngles, fps = 30) {
  if (kneeAngles.length < fps * 2) return { steps: 0, cadence: 0 }

  // 1. Median filter to reduce single-frame noise
  const smoothed = medianFilter(kneeAngles, 5)

  // 2. Adaptive prominence threshold = max(IQR * 0.3, 2.0°)
  const sorted = [...smoothed].sort((a, b) => a - b)
  const q1 = sorted[Math.floor(sorted.length * 0.25)]
  const q3 = sorted[Math.floor(sorted.length * 0.75)]
  const iqr = q3 - q1
  const minProminence = Math.max(iqr * 0.3, 2.0)

  // 3. Window-based peak detection (half-window W=7 at 30fps ≈ 0.23s)
  const W = 7
  const minGapFrames = Math.round(fps * 0.35) // 0.35s = ~170 steps/min max

  const peaks = []
  for (let i = W; i < smoothed.length - W; i++) {
    let isMax = true
    let windowMin = smoothed[i]
    for (let j = i - W; j <= i + W; j++) {
      if (j !== i && smoothed[j] >= smoothed[i]) { isMax = false; break }
      if (smoothed[j] < windowMin) windowMin = smoothed[j]
    }
    if (!isMax) continue
    const prominence = smoothed[i] - windowMin
    if (prominence < minProminence) continue
    if (peaks.length && (i - peaks[peaks.length - 1]) < minGapFrames) continue
    peaks.push(i)
  }

  // 4. Compute cadence from inter-peak intervals
  if (peaks.length < 3) return { steps: peaks.length, cadence: 0 }

  const intervals = []
  for (let i = 1; i < peaks.length; i++) {
    intervals.push((peaks[i] - peaks[i - 1]) / fps)
  }

  // Filter physiologically valid intervals (0.35s - 1.5s per step)
  const validIntervals = intervals.filter(t => t >= 0.35 && t <= 1.5)
  if (!validIntervals.length) return { steps: peaks.length, cadence: 0 }

  const avgInterval = median(validIntervals)
  // avgInterval là 1 chu kỳ dáng đi của MỘT chân (= 2 bước cả hai chân),
  // nên nhân đôi để khớp định nghĩa cadence lâm sàng (steps/min cả 2 chân) —
  // xem cùng công thức đã sửa ở gait_analyzer.py::_gait_cycle_metrics.
  const cadence = Math.round(120 / avgInterval)

  return { steps: peaks.length, cadence }
}

function computeQualityScore(data, filteredCount, originalCount) {
  const retentionRate = filteredCount / originalCount
  const avgCameras = data.reduce((s, f) => s + (f.cameras_active || 1), 0) / data.length
  const avgConfidence = data.reduce((s, f) => {
    const c = f.confidence
    if (!c) return s + 0.5
    const scores = [c.lateral, c.frontal, c.posterior].filter(v => v != null && v > 0)
    return s + (scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0.5)
  }, 0) / data.length

  // Weighted: 40% retention, 30% cameras, 30% confidence
  const score = (retentionRate * 0.4) + (avgCameras / 3 * 0.3) + (avgConfidence * 0.3)
  return {
    score: +Math.min(score, 1.0).toFixed(2),
    grade: score >= 0.7 ? 'good' : score >= 0.4 ? 'fair' : 'poor',
    framesUsed: filteredCount,
    framesDropped: originalCount - filteredCount,
    avgCameras: +avgCameras.toFixed(1),
    avgConfidence: +avgConfidence.toFixed(2),
  }
}

function analyzeRecording(data) {
  if (!data.length) return null
  const originalCount = data.length

  // Step 1: Confidence-based frame filtering
  const filtered = filterByConfidence(data, 0.3, 1)
  if (filtered.length < 30) return null // need at least 1 second of good data

  // Unwrap fused angles
  const frames = filtered[0]?.fused !== undefined ? filtered.map(f => f.fused) : filtered

  // Step 2+3: Per-joint stats with outlier removal and normalization
  const keys = [
    'left_knee','right_knee','left_hip','right_hip','left_ankle','right_ankle','trunk_inclination',
    'left_hip_abduction','right_hip_abduction','lateral_trunk_lean',
    'left_knee_valgus','right_knee_valgus',
    'pelvic_obliquity','left_hip_drop','right_hip_drop',
    'left_foot_progression','right_foot_progression',
  ]

  const joints = {}
  for (const key of keys) {
    let vals = frames.map(d => d[key]).filter(v => v != null)
    if (!vals.length) { joints[key] = null; continue }

    // Normalize pelvic obliquity convention
    if (key === 'pelvic_obliquity') {
      vals = vals.map(normalizePelvicObliquity).filter(v => v != null)
    }

    // Remove outliers (2.5th-97.5th percentile)
    vals = removeOutliers(vals, 2.5, 97.5)
    if (!vals.length) { joints[key] = null; continue }

    joints[key] = computeJointStats(vals)
  }

  // Symmetry index with outlier removal
  const symVals = removeOutliers(
    frames.map(d => d.knee_symmetry_index).filter(v => v != null && v >= 0 && v < 100),
    2.5, 97.5
  )
  const symmetry = symVals.length
    ? { mean: +median(symVals).toFixed(1), max: +percentile([...symVals].sort((a, b) => a - b), 95).toFixed(1) }
    : null

  // Step 4: Cadence — prefer backend-computed values
  const fps = 30
  const durationS = +(filtered.length / fps).toFixed(1)
  let steps, cadence, strideTime = null, stancePhasePct = null, swingPhasePct = null, stepSymmetry = null

  const backendCadence = computeCadenceFromBackendData(filtered)
  if (backendCadence != null) {
    cadence = Math.round(backendCadence)
    steps = Math.round(cadence * durationS / 60)
    // Extract stride/phase metrics from backend stream
    const strides = frames.map(f => f.stride_time).filter(v => v != null && v > 0.4 && v < 3)
    strideTime = strides.length > 5 ? +median(strides).toFixed(2) : null
    const stances = frames.map(f => f.stance_phase_pct).filter(v => v != null && v > 40 && v < 80)
    stancePhasePct = stances.length > 5 ? +median(stances).toFixed(1) : null
    swingPhasePct = stancePhasePct != null ? +(100 - stancePhasePct).toFixed(1) : null
    const syms = frames.map(f => f.step_symmetry).filter(v => v != null && v >= 0 && v < 50)
    stepSymmetry = syms.length > 5 ? +median(syms).toFixed(1) : null
  } else {
    // Fallback: frontend adaptive peak detection on knee angles
    const leftKnee = frames.map(f => f.left_knee).filter(v => v != null)
    const rightKnee = frames.map(f => f.right_knee).filter(v => v != null)
    const leftResult = detectStepsFromKneeAngles(leftKnee, fps)
    const rightResult = detectStepsFromKneeAngles(rightKnee, fps)
    cadence = Math.round((leftResult.cadence + rightResult.cadence) / 2) ||
              (durationS > 0 ? Math.round((leftResult.steps + rightResult.steps) / durationS * 60) : 0)
    // steps suy từ cadence × thời lượng, khớp cách nhánh backendCadence tính
    // (đếm peak riêng từng chân rồi lấy trung bình sẽ ra ~nửa tổng số bước thật).
    steps = durationS > 0 ? Math.round(cadence * durationS / 60) : (leftResult.steps + rightResult.steps)
  }

  // Step 5: Quality score
  const quality = computeQualityScore(filtered, filtered.length, originalCount)

  const camerasUsed = filtered[0]?.cameras_active ??
                      data[0]?.cameras_active ?? 1

  return {
    joints,
    symmetry,
    steps,
    cadence,
    strideTime,
    stancePhasePct,
    swingPhasePct,
    stepSymmetry,
    durationS,
    frames: filtered.length,
    camerasUsed,
    quality,
  }
}

// ── Joint metadata ─────────────────────────────────────────────────────────
const JOINT_META = [
  { key: 'left_knee',              label: 'Gối T',       color: '#3b82f6' },
  { key: 'right_knee',             label: 'Gối P',       color: '#ef4444' },
  { key: 'left_hip',               label: 'Hông T',      color: '#8b5cf6' },
  { key: 'right_hip',              label: 'Hông P',      color: '#f97316' },
  // COCO-17 không có điểm gót/mũi chân — backend trả về độ nghiêng cẳng chân, không phải góc cổ chân.
  { key: 'left_ankle',             label: 'Nghiêng cẳng chân T', color: '#0ea5e9' },
  { key: 'right_ankle',            label: 'Nghiêng cẳng chân P', color: '#f43f5e' },
  { key: 'trunk_inclination',      label: 'Thân',        color: '#10b981' },
  { key: 'knee_symmetry_index',    label: 'Cân xứng',    color: '#a855f7', unit: '%' },
]

const JOINT_META_EXTENDED = [
  ...JOINT_META,
  { key: 'left_hip_abduction',     label: 'Abd T',       color: '#06b6d4' },
  { key: 'right_hip_abduction',    label: 'Abd P',       color: '#0891b2' },
  { key: 'lateral_trunk_lean',     label: 'Lean',        color: '#f59e0b' },
  { key: 'left_knee_valgus',       label: 'Valgus T',    color: '#84cc16' },
  { key: 'right_knee_valgus',      label: 'Valgus P',    color: '#65a30d' },
  { key: 'pelvic_obliquity',       label: 'Chậu',        color: '#d97706' },
  { key: 'left_hip_drop',          label: 'Drop T',      color: '#dc2626', unit: 'px' },
  { key: 'right_hip_drop',         label: 'Drop P',      color: '#b91c1c', unit: 'px' },
  { key: 'left_foot_progression',  label: 'Bàn chân T',  color: '#7c3aed' },
  { key: 'right_foot_progression', label: 'Bàn chân P',  color: '#6d28d9' },
]

// ── Analysis panel ────────────────────────────────────────────────────────────
function AnalysisPanel({ result, onReset, linkedSessionId, camerasUsed }) {
  const [saving, setSaving] = useState(false)
  const [saved,  setSaved]  = useState(false)
  const qc = useQueryClient()

  if (!result) return null

  const handleSave = async () => {
    setSaving(true)
    try {
      await saveCameraSession({
        recorded_at: dayjs().format('YYYY-MM-DDTHH:mm:ss'),
        duration_s: result.durationS,
        frames: result.frames,
        cameras_used: camerasUsed ?? result.camerasUsed ?? 1,
        analysis: result,
      })
      toast.success('Đã lưu kết quả camera')
      setSaved(true)
      qc.invalidateQueries({ queryKey: ['camera-sessions'] })
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Lưu thất bại')
    } finally {
      setSaving(false)
    }
  }

  const romData = JOINT_META_EXTENDED.slice(0, 7)
    .map(m => result.joints[m.key] ? { name: m.label, rom: result.joints[m.key].rom, color: m.color } : null)
    .filter(Boolean)

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl bg-purple-100 flex items-center justify-center">
            <BarChart2 size={16} className="text-purple-600" />
          </div>
          <div>
            <h2 className="font-bold text-gray-800 text-sm">Kết quả phân tích dáng đi</h2>
            <p className="text-xs text-gray-400">{result.frames} frames · {result.durationS}s · {result.camerasUsed ?? 1} camera</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onReset}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 font-medium transition-colors">
            <RotateCcw size={12} /> Ghi lại
          </button>
          <button onClick={handleSave} disabled={saving || saved}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
              saved ? 'bg-green-50 text-green-600 border border-green-200'
              : 'bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50'}`}>
            <Save size={12} /> {saved ? 'Đã lưu' : saving ? 'Đang lưu…' : 'Lưu kết quả'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Thời gian',     value: `${result.durationS}s`,                         color: '#8b5cf6', bg: 'bg-purple-50' },
          { label: 'Frames',        value: result.frames,                                   color: '#64748b', bg: 'bg-gray-50'   },
          { label: 'Số bước',       value: result.steps ?? '—',                             color: '#f97316', bg: 'bg-orange-50' },
          { label: 'Cadence',       value: result.cadence ? `${result.cadence} b/ph` : '—', color: '#10b981', bg: 'bg-emerald-50'},
        ].map(({ label, value, color, bg }) => (
          <div key={label} className={`${bg} rounded-xl p-4 text-center border border-white`}>
            <p className="text-xs text-gray-400 mb-1 font-medium">{label}</p>
            <p className="text-xl font-bold" style={{ color }}>{value}</p>
          </div>
        ))}
      </div>

      {result.symmetry && (
        <div className="flex items-center gap-3 bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-100 rounded-xl px-4 py-3">
          <div className="w-7 h-7 rounded-lg bg-purple-100 flex items-center justify-center shrink-0">
            <Activity size={14} className="text-purple-600" />
          </div>
          <div className="text-sm">
            <span className="text-purple-800 font-semibold">Chỉ số cân xứng gối</span>
            <span className="text-purple-600 mx-2">·</span>
            <span className="text-purple-700">TB: <strong>{result.symmetry.mean}%</strong></span>
            <span className="text-purple-600 mx-2">·</span>
            <span className="text-purple-700">Max: <strong>{result.symmetry.max}%</strong></span>
            <span className={`ml-3 text-xs px-2 py-0.5 rounded-full font-semibold ${
              result.symmetry.mean < 5 ? 'bg-green-100 text-green-700'
              : result.symmetry.mean < 15 ? 'bg-amber-100 text-amber-700'
              : 'bg-red-100 text-red-700'}`}>
              {result.symmetry.mean < 5 ? 'Tốt' : result.symmetry.mean < 15 ? 'Nhẹ lệch' : 'Lệch nhiều'}
            </span>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Biên độ vận động (ROM)</p>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={romData} margin={{ top: 4, right: 4, left: -24, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="name" tick={{ fontSize: 9 }} />
              <YAxis tick={{ fontSize: 9 }} unit="°" />
              <Tooltip formatter={v => [`${v}°`, 'ROM']} contentStyle={{ fontSize: 11, borderRadius: 8, border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
              <Bar dataKey="rom" radius={[4, 4, 0, 0]}>
                {romData.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Chi tiết góc khớp</p>
          <div className="overflow-y-auto max-h-48">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  {['Khớp','TB','Min','Max','ROM'].map(h => (
                    <th key={h} className="text-left py-1.5 pr-2 font-semibold text-gray-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {JOINT_META_EXTENDED.map(m => {
                  const j = result.joints[m.key]
                  if (!j) return null
                  const unit = m.unit ?? '°'
                  return (
                    <tr key={m.key} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                      <td className="py-1.5 pr-2 font-semibold" style={{ color: m.color }}>{m.label}</td>
                      <td className="py-1.5 pr-2 text-gray-700">{j.mean}{unit}</td>
                      <td className="py-1.5 pr-2 text-gray-400">{j.min}{unit}</td>
                      <td className="py-1.5 pr-2 text-gray-400">{j.max}{unit}</td>
                      <td className="py-1.5 font-bold text-gray-800">{j.rom}{unit}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── useCameraStream hook ──────────────────────────────────────────────────────
function useCameraStream({ cameraId, token, onFrame, role = 'lateral' }) {
  const wsRef     = useRef(null)
  const imgRef    = useRef(null)
  const canvasRef = useRef(null)

  const [status,    setStatus]    = useState('disconnected')
  const [error,     setError]     = useState('')
  const [statusMsg, setStatusMsg] = useState('')
  const [resolution, setRes]      = useState(null)
  const [procMs,    setProcMs]    = useState(null)
  const [detected,  setDetected]  = useState(null)
  const [angles,    setAngles]    = useState({})
  const [imu,       setImu]       = useState(null)
  const [depthAtJoints, setDepthAtJoints] = useState({})

  useEffect(() => {
    imgRef.current = new Image()
    imgRef.current.onload = () => {
      const canvas = canvasRef.current
      if (!canvas) return
      canvas.getContext('2d').drawImage(imgRef.current, 0, 0, canvas.width, canvas.height)
    }
  }, [])

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    setStatus('disconnected'); setError(''); setStatusMsg('')
    setRes(null); setProcMs(null); setDetected(null)
    setAngles({}); setImu(null); setDepthAtJoints({})
    const canvas = canvasRef.current
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
  }, [])

  const connect = useCallback(() => {
    if (cameraId == null) return
    disconnect()
    setStatus('connecting'); setError(''); setStatusMsg('Đang mở camera…')
    const ws = new WebSocket(buildWsUrl(cameraId, token, role))
    wsRef.current = ws
    ws.onmessage = (ev) => {
      let data; try { data = JSON.parse(ev.data) } catch { return }
      if (data.type === 'frame') {
        setStatus('connected')
        const a = data.angles || {}
        setAngles(a); setProcMs(data.processing_time_ms); setDetected(data.keypoints_detected)
        if (data.resolution) setRes(data.resolution)
        if (data.imu) setImu(data.imu)
        if (data.depth_at_joints) setDepthAtJoints(data.depth_at_joints)
        if (imgRef.current && data.frame)
          imgRef.current.src = `data:image/jpeg;base64,${data.frame}`
        onFrame?.(a, data)
      } else if (data.type === 'status') {
        setStatus(s => s === 'connected' ? 'connected' : 'connecting')
        setStatusMsg(data.message || '')
        if (data.resolution) setRes(data.resolution)
      } else if (data.type === 'error') {
        setStatus('error'); setError(data.message || 'Lỗi không xác định')
      }
    }
    ws.onerror = () => { setStatus('error'); setError('Không thể kết nối WebSocket.') }
    ws.onclose = () => setStatus(s => s === 'error' ? 'error' : 'disconnected')
  }, [cameraId, token, role, disconnect, onFrame])

  useEffect(() => () => wsRef.current?.close(), [])

  return {
    canvasRef, connect, disconnect,
    isActive: status === 'connected' || status === 'connecting',
    status, error, statusMsg, resolution, procMs, detected,
    angles, imu, depthAtJoints,
  }
}

// ── Role config ───────────────────────────────────────────────────────────────
const ROLE_CONFIG = {
  frontal:   { label: 'Frontal',   sub: 'Nhìn thẳng', gradient: 'from-blue-500 to-blue-600',      badge: 'bg-blue-500'    },
  lateral:   { label: 'Lateral',   sub: 'Nhìn ngang',  gradient: 'from-violet-500 to-purple-600',  badge: 'bg-violet-500'  },
  posterior: { label: 'Posterior', sub: 'Nhìn sau',    gradient: 'from-emerald-500 to-teal-600',   badge: 'bg-emerald-500' },
}

// ── Camera selector dropdown ──────────────────────────────────────────────────
function CameraSelector({ currentId, currentName, detectedCameras, onSelect, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    function handleClick(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const displayName = currentId == null ? 'Chưa chọn camera' : (currentName || String(currentId))

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => !disabled && setOpen(o => !o)}
        disabled={disabled}
        className={`flex items-center gap-1 px-2 py-1 text-xs rounded-lg border transition-colors max-w-[140px] ${
          disabled ? 'opacity-40 cursor-not-allowed' :
          open ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-500 hover:border-gray-300 bg-white'
        }`}
      >
        <Camera size={10} className="shrink-0" />
        <span className="truncate">{displayName}</span>
        <ChevronDown size={10} className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 bg-white rounded-xl shadow-lg border border-gray-100 py-1 min-w-[180px]">
          <div className="px-2 py-1 mb-0.5">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Chọn thiết bị</p>
          </div>

          {/* None option */}
          <button
            onClick={() => { onSelect(null, null); setOpen(false) }}
            className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-50 transition-colors ${
              currentId == null ? 'text-blue-600 font-semibold' : 'text-gray-600'}`}
          >
            <CameraOff size={11} className="shrink-0 text-gray-400" />
            <span>Không dùng</span>
            {currentId == null && <Check size={10} className="ml-auto text-blue-500" />}
          </button>

          {detectedCameras.length > 0 && <div className="border-t border-gray-100 my-1" />}

          {detectedCameras.map((cam) => {
            const camId = cam.type === 'realsense' ? 'realsense' : cam.index
            const isSelected = currentId === camId
            return (
              <button
                key={camId}
                onClick={() => { onSelect(camId, cam.name); setOpen(false) }}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-gray-50 transition-colors ${
                  isSelected ? 'text-blue-600 font-semibold' : 'text-gray-700'}`}
              >
                <Camera size={11} className={`shrink-0 ${isSelected ? 'text-blue-500' : 'text-gray-400'}`} />
                <div className="flex flex-col min-w-0">
                  <span className="truncate">{cam.name || `Camera ${cam.index}`}</span>
                  {cam.width && (
                    <span className="text-gray-400 font-normal">{cam.width}×{cam.height}</span>
                  )}
                </div>
                {isSelected && <Check size={10} className="ml-auto shrink-0 text-blue-500" />}
              </button>
            )
          })}

          {detectedCameras.length === 0 && (
            <p className="px-3 py-2 text-xs text-gray-400 italic">Chưa quét thiết bị</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Camera panel ──────────────────────────────────────────────────────────────
function CameraPanel({ role, cameraId, cameraName, token, onFrame, recordState, recordedRef, isMain, detectedCameras, onCameraChange, onStreamStatus }) {
  const [showDepth, setShowDepth] = useState(false)
  const depthImgRef    = useRef(null)
  const depthCanvasRef = useRef(null)

  useEffect(() => {
    depthImgRef.current = new Image()
    depthImgRef.current.onload = () => {
      const canvas = depthCanvasRef.current
      if (!canvas) return
      canvas.getContext('2d').drawImage(depthImgRef.current, 0, 0, canvas.width, canvas.height)
    }
  }, [])

  const handleFrame = useCallback((a, data) => {
    if (data.depth_frame && depthImgRef.current)
      depthImgRef.current.src = `data:image/jpeg;base64,${data.depth_frame}`
    onFrame?.(a, data)
  }, [onFrame])

  const stream = useCameraStream({ cameraId, token, onFrame: handleFrame, role })
  const cfg    = ROLE_CONFIG[role] || ROLE_CONFIG.frontal

  useEffect(() => {
    onStreamStatus?.(role, stream.status)
  }, [role, stream.status, onStreamStatus])

  return (
    <div className="flex-1 flex flex-col gap-2 min-w-0">
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        <div className={`h-1 w-full bg-gradient-to-r ${cfg.gradient}`} />

        <div className="px-3 pt-2.5 pb-2">
          {/* Title row */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className={`text-white text-xs font-bold px-2 py-0.5 rounded-lg shrink-0 ${cfg.badge}`}>
                {cfg.label}
              </span>
              <p className="text-xs font-semibold text-gray-700 leading-none">{cfg.sub}</p>
            </div>
            <div className="flex items-center gap-1.5">
              {cameraId === 'realsense' && stream.status === 'connected' && (
                <button onClick={() => setShowDepth(d => !d)}
                  className={`flex items-center gap-1 px-2 py-1 text-xs rounded-lg font-medium border transition-colors ${
                    showDepth ? 'bg-cyan-500 border-cyan-500 text-white' : 'border-gray-200 text-gray-500 hover:border-cyan-300'}`}>
                  <Layers size={10} /> Depth
                </button>
              )}
              {stream.isActive ? (
                <button onClick={stream.disconnect}
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-red-50 text-red-500 hover:bg-red-100 font-semibold border border-red-100 transition-colors">
                  <WifiOff size={11} /> Ngắt
                </button>
              ) : (
                <button onClick={stream.connect} disabled={cameraId == null}
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-blue-500 text-white hover:bg-blue-600 font-semibold disabled:opacity-40 transition-colors">
                  <Wifi size={11} /> Kết nối
                </button>
              )}
            </div>
          </div>

          {/* Camera selector row */}
          <div className="flex items-center justify-between">
            <CameraSelector
              currentId={cameraId}
              currentName={cameraName}
              detectedCameras={detectedCameras}
              onSelect={onCameraChange}
              disabled={stream.isActive}
            />
            {/* Status */}
            <div className="flex items-center gap-2 flex-wrap justify-end">
              {stream.status === 'connected' && (
                <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live
                </span>
              )}
              {stream.status === 'connecting' && (
                <span className="flex items-center gap-1 text-xs text-amber-600 font-medium">
                  <RefreshCw size={10} className="animate-spin" /> Kết nối…
                </span>
              )}
              {stream.status === 'disconnected' && (
                <span className="text-xs text-gray-400">Chưa kết nối</span>
              )}
              {stream.status === 'error' && (
                <span className="text-xs text-red-500 truncate max-w-[120px]">{stream.error}</span>
              )}
              {stream.resolution && stream.status === 'connected' && (
                <span className="text-xs text-gray-400 font-mono">{stream.resolution.width}×{stream.resolution.height}</span>
              )}
              {stream.status === 'connected' && stream.procMs != null && (
                <span className="text-xs text-gray-400">{stream.procMs}ms</span>
              )}
              {stream.status === 'connected' && stream.detected != null && (
                <span className="text-xs text-gray-400">{stream.detected}/25 kp</span>
              )}
              {isMain && recordState === 'recording' && (
                <span className="flex items-center gap-1 text-xs text-red-600 font-bold">
                  <Circle size={8} className="fill-red-500 text-red-500 animate-pulse" />
                  REC {recordedRef?.current?.length ?? 0}f
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Video area */}
        <div className="relative bg-gray-950 overflow-hidden" style={{ aspectRatio: '16/9' }}>
          <canvas ref={stream.canvasRef} width={1280} height={720}
            className={`w-full h-full object-contain ${showDepth ? 'hidden' : ''}`} />
          {cameraId === 'realsense' && (
            <canvas ref={depthCanvasRef} width={1280} height={720}
              className={`w-full h-full object-contain ${showDepth ? '' : 'hidden'}`} />
          )}

          {stream.status !== 'connected' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-white/5 flex items-center justify-center">
                <Video size={22} className="text-gray-600" />
              </div>
              {stream.status === 'connecting' && stream.statusMsg ? (
                <p className="text-xs text-gray-500 text-center max-w-[160px] leading-relaxed">{stream.statusMsg}</p>
              ) : stream.status === 'disconnected' ? (
                <p className="text-xs text-gray-600">
                  {cameraId == null ? 'Camera chưa được phát hiện' : 'Nhấn Kết nối để bắt đầu'}
                </p>
              ) : null}
            </div>
          )}

          {showDepth && stream.status === 'connected' && (
            <div className="absolute top-2 right-2 bg-cyan-500/90 text-white text-xs px-2 py-0.5 rounded-full font-bold backdrop-blur-sm">
              DEPTH
            </div>
          )}
        </div>

        {/* RealSense IMU strip */}
        {cameraId === 'realsense' && stream.imu && stream.status === 'connected' && (
          <div className="grid grid-cols-2 gap-2 px-3 py-2 bg-gray-50 border-t border-gray-100">
            <div>
              <p className="text-xs text-gray-400 font-semibold mb-0.5">Accel (m/s²)</p>
              <p className="text-xs text-gray-600 font-mono">
                {stream.imu.accel.map((v, i) => `${['X','Y','Z'][i]}:${v}`).join(' ')}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 font-semibold mb-0.5">Gyro (rad/s)</p>
              <p className="text-xs text-gray-600 font-mono">
                {stream.imu.gyro.map((v, i) => `${['X','Y','Z'][i]}:${v}`).join(' ')}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CameraAnalysis() {
  const { token } = useAuthStore()
  const navigate = useNavigate()
  const { pushFrame, getFusedFrame } = useFusionBuffer()

  const [selectedHistoryItem, setSelectedHistoryItem] = useState(null)

  const [cameras, setCameras] = useState([
    { id: null, name: 'Brio 300',            role: 'frontal',   isMain: false },
    { id: 'realsense', name: 'RealSense D435i', role: 'lateral',   isMain: true  },
    { id: null, name: 'Brio 300',            role: 'posterior', isMain: false },
  ])
  const [detectedCameras, setDetectedCameras] = useState([])

  const [recordState,    setRecordState]    = useState('idle')
  const recordedRef    = useRef([])
  const analysisRef    = useRef(null)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [showAnalysis,   setShowAnalysis]   = useState(false)
  const [liveAngles,     setLiveAngles]     = useState({})
  const [liveHistory,    setLiveHistory]    = useState([])
  const [scanning,       setScanning]       = useState(false)
  const [fusionStatus,   setFusionStatus]   = useState({ lateral: 0, frontal: 0, posterior: 0, cameras_active: 0 })
  const [linkedSessionId, setLinkedSessionId] = useState(null)
  const [activeTab,      setActiveTab]      = useState('analyze')
  const [connectedCameras, setConnectedCameras] = useState({})

  const handleStreamStatus = useCallback((role, status) => {
    setConnectedCameras(prev => ({ ...prev, [role]: status === 'connected' }))
  }, [])

  const anyCameraConnected = Object.values(connectedCameras).some(Boolean)

  const { data: imuSessionsData } = useQuery({
    queryKey: ['sessions', 'completed'],
    queryFn: () => getSessions({ status: 'completed', page_size: 20 }),
    select: d => d?.data?.items ?? [],
  })
  const imuSessions = imuSessionsData ?? []

  const { data: cameraHistoryData, refetch: refetchHistory } = useQuery({
    queryKey: ['camera-sessions'],
    queryFn: () => listCameraSessions({ page_size: 50 }),
    select: d => d?.data?.items ?? [],
  })
  const cameraHistory = cameraHistoryData ?? []

  const deleteCS = useMutation({
    mutationFn: deleteCameraSession,
    onSuccess: () => { toast.success('Đã xoá'); refetchHistory() },
    onError: () => toast.error('Xoá thất bại'),
  })

  const applyFusedFrame = useCallback(() => {
    const fusedFrame = getFusedFrame()
    if (!fusedFrame) return
    const fused = fusedFrame.fused
    setLiveAngles(fused)
    setLiveHistory(prev => {
      const next = [...prev, { t: prev.length, ...fused }]
      return next.length > MAX_HISTORY ? next.slice(-MAX_HISTORY) : next
    })
    setFusionStatus({ ...fusedFrame.confidence, cameras_active: fusedFrame.cameras_active })
    setRecordState(rs => {
      if (rs === 'recording' && recordedRef.current.length < RECORD_LIMIT)
        recordedRef.current.push(fusedFrame)
      return rs
    })
  }, [getFusedFrame])

  const handleFrontalFrame = useCallback((a, data) => {
    pushFrame('frontal', data)
    applyFusedFrame()
  }, [pushFrame, applyFusedFrame])

  const handleLateralFrame = useCallback((a, data) => {
    pushFrame('lateral', data)
    applyFusedFrame()
  }, [pushFrame, applyFusedFrame])

  const handlePosteriorFrame = useCallback((a, data) => {
    pushFrame('posterior', data)
    applyFusedFrame()
  }, [pushFrame, applyFusedFrame])

  const scanDevices = useCallback(async (manual = false) => {
    setScanning(true)
    try {
      const res  = await (manual ? scanCameras : listCameras)({ timeout: 40000 })
      const list = res.data.cameras || []
      setDetectedCameras(list)
      const rs    = list.find(c => c.type === 'realsense' || c.name?.toLowerCase().includes('realsense'))
      const brios = list.filter(c => c.name?.toLowerCase().includes('brio') || (c.width >= 1920 && c.height >= 1080))
      setCameras(prev => prev.map(cam => {
        if (cam.role === 'lateral')   return rs       ? { ...cam, id: 'realsense',    name: rs.name }       : { ...cam, id: null }
        if (cam.role === 'frontal')   return brios[0] ? { ...cam, id: brios[0].index, name: brios[0].name } : cam
        if (cam.role === 'posterior') return brios[1] ? { ...cam, id: brios[1].index, name: brios[1].name } : cam
        return cam
      }))
    } catch { /* ignore */ }
    finally { setScanning(false) }
  }, [])

  useEffect(() => { scanDevices() }, [scanDevices])

  const handleCameraChange = useCallback((role, newId, newName) => {
    setCameras(prev => prev.map(cam =>
      cam.role === role ? { ...cam, id: newId, name: newName } : cam
    ))
  }, [])

  const startRecording  = useCallback(() => { recordedRef.current = []; setRecordState('recording'); setAnalysisResult(null); setShowAnalysis(false) }, [])
  const pauseRecording  = useCallback(() => setRecordState('paused'),    [])
  const resumeRecording = useCallback(() => setRecordState('recording'), [])
  const runAnalysis = useCallback(() => {
    setAnalysisResult(analyzeRecording(recordedRef.current))
    setShowAnalysis(true)
    setRecordState('idle')
    setTimeout(() => analysisRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
  }, [])
  const resetRecording  = useCallback(() => { recordedRef.current = []; setRecordState('idle'); setAnalysisResult(null); setShowAnalysis(false) }, [])

  const hasData    = recordedRef.current.length > 10
  const frameCount = recordedRef.current.length

  useEffect(() => {
    if (recordState === 'recording' && frameCount >= AUTO_STOP_FRAMES) {
      toast.success('Đã tự động dừng ghi sau 1 phút 30 giây')
      runAnalysis()
    }
  }, [recordState, frameCount, runAnalysis])

  const frameHandlers = {
    frontal:   handleFrontalFrame,
    lateral:   handleLateralFrame,
    posterior: handlePosteriorFrame,
  }

  const frontCam    = cameras.find(c => c.role === 'frontal')
  const lateralCam  = cameras.find(c => c.role === 'lateral')
  const posteriorCam = cameras.find(c => c.role === 'posterior')

  return (
    <div className="p-5 space-y-4 bg-gray-50 min-h-screen">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Phân tích bằng Camera</h1>
          <p className="text-xs text-gray-500 mt-0.5">YOLOv8-Pose · COCO-17 ánh xạ Body-25 · 3 góc nhìn · RealSense D435i + 2× Brio 300</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Tab switcher */}
          <div className="flex items-center bg-gray-100 rounded-xl p-1 gap-1">
            <button onClick={() => setActiveTab('analyze')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                activeTab === 'analyze' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              <FlaskConical size={12} /> Phân tích
            </button>
            <button onClick={() => setActiveTab('history')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                activeTab === 'history' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
              <History size={12} /> Lịch sử {cameraHistory.length > 0 && `(${cameraHistory.length})`}
            </button>
          </div>
          <button onClick={() => scanDevices(true)} disabled={scanning || activeTab === 'history'}
            className="flex items-center gap-2 px-4 py-2 text-sm rounded-xl border border-gray-200 bg-white hover:bg-gray-50 text-gray-600 font-medium shadow-sm disabled:opacity-50 transition-colors">
            <ScanLine size={14} className={scanning ? 'animate-pulse text-blue-500' : 'text-gray-400'} />
            {scanning ? 'Đang quét…' : 'Quét camera'}
          </button>
        </div>
      </div>

      {activeTab === 'history' ? (
        /* ── History tab ── */
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <p className="font-semibold text-gray-800 text-sm">Lịch sử đo bằng Camera</p>
            <span className="text-xs text-gray-400">{cameraHistory.length} bản ghi</span>
          </div>
          {cameraHistory.length === 0 ? (
            <div className="py-16 text-center text-gray-400 text-sm">Chưa có dữ liệu lưu</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-400 uppercase tracking-wide">
                  {['Ngày giờ','Thời lượng','Frames','Camera',''].map(h => (
                    <th key={h} className="text-left px-4 py-2.5 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cameraHistory.map(cs => (
                  <Fragment key={cs.id}>
                  <tr
                    onClick={() => setSelectedHistoryItem(sel => sel?.id === cs.id ? null : cs)}
                    className="border-b border-gray-50 hover:bg-violet-50 transition-colors cursor-pointer">
                    <td className="px-4 py-2.5 text-gray-700">{dayjs(cs.recorded_at).format('DD/MM/YYYY HH:mm')}</td>
                    <td className="px-4 py-2.5 text-gray-600">{cs.duration_s ? `${cs.duration_s}s` : '—'}</td>
                    <td className="px-4 py-2.5 text-gray-600">{cs.frames ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className="px-2 py-0.5 bg-violet-50 text-violet-700 rounded-full text-xs font-semibold">
                        {cs.cameras_used} cam
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <button onClick={e => { e.stopPropagation(); deleteCS.mutate(cs.id) }}
                        className="text-gray-300 hover:text-red-400 transition-colors">
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                  {selectedHistoryItem?.id === cs.id && cs.analysis && (
                    <tr key={`detail-${cs.id}`}>
                      <td colSpan={5} className="px-4 pb-4 pt-0 bg-gray-50">
                        <div className="rounded-xl border border-violet-100 bg-white p-4 space-y-3">
                          <div className="flex items-center justify-between">
                            <p className="text-xs font-bold text-violet-700 uppercase tracking-wide">Chi tiết phân tích</p>
                          </div>
                          {/* Summary stats */}
                          <div className="grid grid-cols-4 gap-2">
                            {[
                              { label: 'Thời gian', value: `${cs.analysis.durationS}s` },
                              { label: 'Frames',    value: cs.analysis.frames },
                              { label: 'Số bước',   value: cs.analysis.steps ?? '—' },
                              { label: 'Cadence',   value: cs.analysis.cadence ? `${cs.analysis.cadence} b/ph` : '—' },
                            ].map(({ label, value }) => (
                              <div key={label} className="bg-gray-50 rounded-lg p-2 text-center">
                                <p className="text-[10px] text-gray-400">{label}</p>
                                <p className="text-sm font-bold text-gray-700">{value}</p>
                              </div>
                            ))}
                          </div>
                          {/* Symmetry indicator */}
                          {cs.analysis.symmetry && (
                            <div className="flex items-center gap-3 bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-100 rounded-xl px-4 py-3">
                              <div className="w-7 h-7 rounded-lg bg-purple-100 flex items-center justify-center shrink-0">
                                <Activity size={14} className="text-purple-600" />
                              </div>
                              <div className="text-sm">
                                <span className="text-purple-800 font-semibold">Chỉ số cân xứng gối</span>
                                <span className="text-purple-600 mx-2">·</span>
                                <span className="text-purple-700">TB: <strong>{cs.analysis.symmetry.mean}%</strong></span>
                                <span className="text-purple-600 mx-2">·</span>
                                <span className="text-purple-700">Max: <strong>{cs.analysis.symmetry.max}%</strong></span>
                                <span className={`ml-3 text-xs px-2 py-0.5 rounded-full font-semibold ${
                                  cs.analysis.symmetry.mean < 5 ? 'bg-green-100 text-green-700'
                                  : cs.analysis.symmetry.mean < 15 ? 'bg-amber-100 text-amber-700'
                                  : 'bg-red-100 text-red-700'}`}>
                                  {cs.analysis.symmetry.mean < 5 ? 'Tốt' : cs.analysis.symmetry.mean < 15 ? 'Nhẹ lệch' : 'Lệch nhiều'}
                                </span>
                              </div>
                            </div>
                          )}
                          {/* ROM chart + Joint table */}
                          {cs.analysis.joints && (() => {
                            const histRomData = JOINT_META_EXTENDED.slice(0, 7)
                              .map(m => cs.analysis.joints[m.key] ? { name: m.label, rom: cs.analysis.joints[m.key].rom, color: m.color } : null)
                              .filter(Boolean)
                            return (
                              <div className="grid grid-cols-2 gap-6">
                                <div>
                                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Biên độ vận động (ROM)</p>
                                  <ResponsiveContainer width="100%" height={160}>
                                    <BarChart data={histRomData} margin={{ top: 4, right: 4, left: -24, bottom: 4 }}>
                                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                                      <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                                      <YAxis tick={{ fontSize: 9 }} unit="°" />
                                      <Tooltip formatter={v => [`${v}°`, 'ROM']} contentStyle={{ fontSize: 11, borderRadius: 8, border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                                      <Bar dataKey="rom" radius={[4, 4, 0, 0]}>
                                        {histRomData.map((d, i) => <Cell key={i} fill={d.color} />)}
                                      </Bar>
                                    </BarChart>
                                  </ResponsiveContainer>
                                </div>
                                <div>
                                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Chi tiết góc khớp</p>
                                  <div className="overflow-y-auto max-h-48">
                                    <table className="w-full text-xs">
                                      <thead>
                                        <tr className="border-b border-gray-100">
                                          {['Khớp','TB','Min','Max','ROM'].map(h => (
                                            <th key={h} className="text-left py-1.5 pr-3 font-semibold text-gray-400">{h}</th>
                                          ))}
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {JOINT_META_EXTENDED.map(m => {
                                          const j = cs.analysis.joints[m.key]
                                          if (!j) return null
                                          const unit = m.unit ?? '°'
                                          return (
                                            <tr key={m.key} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                                              <td className="py-1.5 pr-3 font-semibold" style={{ color: m.color }}>{m.label}</td>
                                              <td className="py-1.5 pr-3 text-gray-700">{j.mean}{unit}</td>
                                              <td className="py-1.5 pr-3 text-gray-400">{j.min}{unit}</td>
                                              <td className="py-1.5 pr-3 text-gray-400">{j.max}{unit}</td>
                                              <td className="py-1.5 font-bold text-gray-800">{j.rom}{unit}</td>
                                            </tr>
                                          )
                                        })}
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              </div>
                            )
                          })()}
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <>
      {/* ── Main layout: cameras left + sidebar right (sticky) ── */}
      <div className="flex gap-4 items-start">

        {/* ── Left: 3 cameras in 2-column grid ── */}
        <div className="flex-1 min-w-0 grid grid-cols-2 gap-3 items-start">
          {[frontCam, lateralCam, posteriorCam].map(cam => cam && (
            <CameraPanel
              key={cam.role}
              role={cam.role}
              cameraId={cam.id}
              cameraName={cam.name}
              token={token}
              onFrame={frameHandlers[cam.role]}
              recordState={recordState}
              recordedRef={cam.isMain ? recordedRef : undefined}
              isMain={cam.isMain}
              detectedCameras={detectedCameras}
              onCameraChange={(id, name) => handleCameraChange(cam.role, id, name)}
              onStreamStatus={handleStreamStatus}
            />
          ))}
          {/* empty 4th slot keeps Posterior aligned with Frontal */}
          <div />
        </div>

        {/* ── Sidebar (sticky) ── */}
        <div className="w-[340px] shrink-0 flex flex-col gap-3 sticky top-4 max-h-[calc(100vh-5rem)] overflow-y-auto">

          {/* Recording card */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-4 pt-3 pb-1">
              <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">Ghi dữ liệu</p>
            </div>
            <div className="px-3 pb-3 flex flex-col gap-2">
              {recordState === 'idle' && (
                <button onClick={startRecording} disabled={!anyCameraConnected}
                  title={!anyCameraConnected ? 'Kết nối ít nhất 1 camera trước' : ''}
                  className="flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-xl bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600 text-white text-sm font-bold shadow-sm shadow-green-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none">
                  <Play size={14} /> Bắt đầu phân tích
                </button>
              )}
              {!anyCameraConnected && recordState === 'idle' && (
                <p className="text-xs text-amber-600 text-center">Kết nối ít nhất 1 camera để bắt đầu</p>
              )}
              {recordState === 'recording' && (
                <>
                  <div className="flex items-center justify-between bg-red-50 rounded-xl px-3 py-2 border border-red-100">
                    <div className="flex items-center gap-1.5">
                      <Circle size={8} className="fill-red-500 text-red-500 animate-pulse" />
                      <span className="text-xs font-bold text-red-600">Đang ghi</span>
                    </div>
                    <span className="text-xs text-red-500 font-mono">{frameCount}f</span>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={pauseRecording}
                      className="flex items-center justify-center gap-1.5 flex-1 px-3 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm font-bold transition-colors">
                      <Pause size={14} /> Tạm dừng
                    </button>
                    <button onClick={runAnalysis}
                      className="flex items-center justify-center gap-1.5 flex-1 px-3 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-violet-600 hover:from-purple-700 hover:to-violet-700 text-white text-sm font-bold transition-colors">
                      <BarChart2 size={14} /> Dừng & Phân tích
                    </button>
                  </div>
                </>
              )}
              {recordState === 'paused' && (
                <>
                  <div className="flex items-center justify-between bg-amber-50 rounded-xl px-3 py-2 border border-amber-100">
                    <span className="text-xs font-semibold text-amber-700">⏸ Đã dừng</span>
                    <span className="text-xs text-amber-600 font-mono">{frameCount}f · {(frameCount/30).toFixed(1)}s</span>
                  </div>
                  <button onClick={resumeRecording}
                    className="flex items-center justify-center gap-2 w-full px-4 py-2 rounded-xl bg-green-500 hover:bg-green-600 text-white text-xs font-bold transition-colors">
                    <Play size={12} /> Tiếp tục
                  </button>
                  {hasData && (
                    <button onClick={runAnalysis}
                      className="flex items-center justify-center gap-2 w-full px-4 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-violet-600 hover:from-purple-700 hover:to-violet-700 text-white text-xs font-bold shadow-sm shadow-purple-200 transition-all">
                      <BarChart2 size={12} /> Phân tích ngay
                    </button>
                  )}
                  <button onClick={resetRecording}
                    className="flex items-center justify-center gap-2 w-full px-4 py-2 rounded-xl border border-gray-200 text-gray-500 hover:bg-gray-50 text-xs font-medium transition-colors">
                    <RotateCcw size={12} /> Đặt lại
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Fusion status */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-4 py-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">
                Fusion · {fusionStatus.cameras_active}/3 camera
              </p>
              {fusionStatus.has_3d && (
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                      style={{ background: '#8b5cf620', color: '#8b5cf6' }}>
                  3D DEPTH
                </span>
              )}
            </div>
            {[
              { role: 'lateral',   label: 'Lateral (RS)',  color: '#8b5cf6' },
              { role: 'frontal',   label: 'Frontal',       color: '#3b82f6' },
              { role: 'posterior', label: 'Posterior',     color: '#10b981' },
            ].map(({ role, label, color }) => {
              const pct = Math.round((fusionStatus[role] ?? 0) * 100)
              return (
                <div key={role} className="flex items-center gap-2 mb-1.5">
                  <span className="text-xs text-gray-500 w-24 shrink-0">{label}</span>
                  <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-300"
                         style={{ width: `${pct}%`, backgroundColor: color }} />
                  </div>
                  <span className="text-xs font-mono text-gray-400 w-8 text-right">{pct}%</span>
                </div>
              )
            })}
          </div>

          {/* Angle cards */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm">
            <div className="px-4 pt-3 pb-1">
              <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">
                Góc khớp · {fusionStatus.has_3d ? 'Fused 3D' : 'Fused'}
              </p>
            </div>
            <div className="px-3 pb-3 grid grid-cols-2 gap-2">
              {JOINT_META.map(({ key, label, color, unit = '°' }) => {
                const val = liveAngles[key]
                return (
                  <div key={key} className="rounded-xl p-2.5 text-center"
                    style={{ background: `${color}0d`, border: `1px solid ${color}20` }}>
                    <p className="text-xs text-gray-500 font-medium leading-none mb-1.5">{label}</p>
                    <p className="text-base font-extrabold leading-none" style={{ color }}>
                      {val != null ? `${val}${unit}` : '—'}
                    </p>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Live chart */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm">
            <div className="px-4 pt-3 pb-1">
              <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">Góc gối live</p>
            </div>
            <div className="px-2 pb-3">
              {liveHistory.length > 3 ? (
                <ResponsiveContainer width="100%" height={110}>
                  <LineChart data={liveHistory} margin={{ top: 2, right: 4, left: -28, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="t" hide />
                    <YAxis domain={[50, 200]} tick={{ fontSize: 8 }} />
                    <Tooltip contentStyle={{ fontSize: 10, borderRadius: 8, border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                      formatter={(v, n) => [v != null ? `${v}°` : '—', n]} />
                    <Line type="monotone" dataKey="left_knee"  name="Gối T" stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />
                    <Line type="monotone" dataKey="right_knee" name="Gối P" stroke="#ef4444" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls />
                    <Legend wrapperStyle={{ fontSize: 9, paddingTop: 4 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[110px] flex items-center justify-center">
                  <p className="text-xs text-gray-300">Chờ dữ liệu từ RealSense…</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Analysis results ── */}
      {showAnalysis && analysisResult && (
        <div ref={analysisRef}>
          <AnalysisPanel
            result={analysisResult}
            onReset={resetRecording}
            linkedSessionId={linkedSessionId}
            camerasUsed={fusionStatus.cameras_active}
          />
        </div>
      )}
      </>
      )}
    </div>
  )
}
