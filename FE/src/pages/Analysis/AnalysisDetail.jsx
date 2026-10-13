import { useMemo, useState, useEffect } from 'react'
import { useParams, Link, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Activity, Camera, RefreshCw } from 'lucide-react'
import dayjs from 'dayjs'
import {
  LineChart, Line, BarChart, Bar, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import {
  getSession, getAnalysis, getChartTimeseries,
  getChartROM, getChartSymmetry, getChartPhase, getChartGaitCycle,
  analyzeSession,
} from '../../api/sessions'
import { listCameraSessions } from '../../api/cameraSessions'
import Card from '../../components/ui/Card'
import ScoreRing from '../../components/Analysis/ScoreRing'
import StatRow from '../../components/Analysis/StatRow'
import ReferenceSection from '../../components/Analysis/ReferenceSection'
import GaitCyclePercentChart from '../../components/Charts/GaitCyclePercentChart'
import { COLORS, COLORS2, seriesLabel, seriesColor } from '../../utils/jointSeries'
import { buildAveragedCycles } from '../../utils/gaitCycle'

function ScoreBreakdown({ breakdown }) {
  if (!breakdown || !breakdown.items?.length) return null
  return (
    <div className="mt-4 pt-4 border-t border-gray-100">
      <p className="text-[11px] text-gray-400 mb-2">
        Bắt đầu {breakdown.base_score} điểm, trừ theo độ lệch ROM &amp; mất đối xứng:
      </p>
      <div className="space-y-1.5">
        {breakdown.items.map((item) => (
          <div key={item.label} className="flex items-center justify-between text-xs">
            <div className="min-w-0">
              <span className="text-gray-600">{item.label}</span>
              {item.value != null && (
                <span className="text-gray-400">
                  {' '}({item.value}{item.unit}{item.norm != null && item.norm !== 0 ? ` / chuẩn ${item.norm}${item.unit}` : ''})
                </span>
              )}
            </div>
            <span className={`font-semibold shrink-0 ml-2 ${item.penalty === 0 ? 'text-green-600' : item.penalty >= item.max_penalty ? 'text-red-600' : 'text-amber-600'}`}>
              -{item.penalty}
            </span>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between text-xs font-semibold mt-2 pt-2 border-t border-gray-100">
        <span className="text-gray-700">Tổng trừ</span>
        <span className="text-red-600">-{breakdown.total_penalty}</span>
      </div>
      <p className="text-[10px] text-gray-400 mt-2">
        ROM: min(|đo - chuẩn|/2, 15) · SI: min(SI/10, 10). Thiếu dữ liệu ROM → phạt 15; thiếu SI → phạt 5.
      </p>
    </div>
  )
}


function TimeseriesChart({ timeseries, seriesNames }) {
  const [hidden, setHidden] = useState({})
  const toggle = (name) => setHidden((p) => ({ ...p, [name]: !p[name] }))

  return (
    <Card title="Góc khớp theo thời gian">
      {/* Custom legend */}
      <div className="flex flex-wrap gap-x-5 gap-y-1.5 mb-3">
        {seriesNames.map((name, i) => (
          <button key={name} onClick={() => toggle(name)}
            className={`flex items-center gap-1.5 text-xs transition-opacity ${hidden[name] ? 'opacity-25' : 'opacity-100'}`}>
            <svg width="22" height="10">
              <line x1="0" y1="5" x2="22" y2="5" stroke={seriesColor(name, i)} strokeWidth="2.5" />
            </svg>
            <span className="font-medium" style={{ color: seriesColor(name, i) }}>{seriesLabel(name)}</span>
          </button>
        ))}
        <span className="text-[10px] text-gray-400 self-center ml-auto italic">click để ẩn/hiện</span>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={timeseries} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="t" tickFormatter={(v) => `${(v / 1000).toFixed(0)}s`} tick={{ fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis unit="°" tick={{ fontSize: 11 }} width={40} />
          <Tooltip
            formatter={(v, name) => [`${Number(v).toFixed(1)}°`, seriesLabel(name)]}
            labelFormatter={(v) => `t=${(v / 1000).toFixed(1)}s`}
            contentStyle={{ fontSize: 11 }}
          />
          {seriesNames.map((name, i) => (
            <Line key={name} type="monotone" dataKey={name}
              stroke={seriesColor(name, i)} strokeWidth={1.5}
              dot={false} isAnimationActive={false}
              hide={!!hidden[name]} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </Card>
  )
}

// ── ComparePanel ─────────────────────────────────────────────────────────────

const AGREE_CFG = {
  good:        { label: 'Tốt',         bg: 'bg-green-100',  color: 'text-green-700' },
  acceptable:  { label: 'Chấp nhận',   bg: 'bg-amber-100',  color: 'text-amber-700' },
  different:   { label: 'Khác biệt',   bg: 'bg-red-100',    color: 'text-red-700'   },
}

function agreementBadge(imu, cam) {
  if (imu == null || cam == null) return null
  const avg = (Math.abs(imu) + Math.abs(cam)) / 2
  const pct = avg === 0 ? 0 : (Math.abs(imu - cam) / avg) * 100
  const cfg = pct < 10 ? AGREE_CFG.good : pct < 20 ? AGREE_CFG.acceptable : AGREE_CFG.different
  return { ...cfg, pct }
}

function symmetryIndex(left, right) {
  if (left == null || right == null) return null
  const denom = Math.abs(left) + Math.abs(right)
  if (denom === 0) return 0
  return (2 * Math.abs(left - right) / denom) * 100
}

function ComparePanel({ sessionId, imuAnalysis, imuGc, onClose }) {
  const [selectedCamId, setSelectedCamId] = useState(null)

  const { data: csListData, isLoading } = useQuery({
    queryKey: ['camera-sessions-all'],
    queryFn: () => listCameraSessions({ page_size: 50 }),
  })

  const csList = csListData?.data?.items ?? []

  const selectedCs = selectedCamId
    ? csList.find(c => c.id === selectedCamId)
    : csList[0]

  const camAnalysis = selectedCs?.analysis

  // IMU values from analysis
  const imu = {
    romKneeL:  imuAnalysis?.left_knee_stats?.rom,
    romKneeR:  imuAnalysis?.right_knee_stats?.rom,
    romHipL:   imuAnalysis?.left_hip_stats?.rom,
    romHipR:   imuAnalysis?.right_hip_stats?.rom,
    siKnee:    imuAnalysis?.symmetry_index_knee,
    cadenceL:  imuGc?.left?.cadence_steps_per_min,
    cadenceR:  imuGc?.right?.cadence_steps_per_min,
  }
  imu.asymKnee = symmetryIndex(imu.romKneeL, imu.romKneeR)
  imu.asymHip  = symmetryIndex(imu.romHipL,  imu.romHipR)

  // Camera values from saved analysis JSON
  const cam = {
    romKneeL:  camAnalysis?.joints?.left_knee?.rom,
    romKneeR:  camAnalysis?.joints?.right_knee?.rom,
    romHipL:   camAnalysis?.joints?.left_hip?.rom,
    romHipR:   camAnalysis?.joints?.right_hip?.rom,
    siKnee:    camAnalysis?.symmetry?.mean,
    cadenceL:  camAnalysis?.cadence,
    cadenceR:  camAnalysis?.cadence,
  }
  cam.asymKnee = symmetryIndex(cam.romKneeL, cam.romKneeR)
  cam.asymHip  = symmetryIndex(cam.romHipL,  cam.romHipR)

  const rows = [
    { label: 'ROM Gối Trái (°)',   imu: imu.romKneeL, cam: cam.romKneeL },
    { label: 'ROM Gối Phải (°)',   imu: imu.romKneeR, cam: cam.romKneeR },
    { label: 'ROM Hông Trái (°)',  imu: imu.romHipL,  cam: cam.romHipL  },
    { label: 'ROM Hông Phải (°)',  imu: imu.romHipR,  cam: cam.romHipR  },
    { label: 'Bất đối xứng Gối (%)', imu: imu.asymKnee, cam: cam.asymKnee, unit: '%' },
    { label: 'Bất đối xứng Hông (%)', imu: imu.asymHip,  cam: cam.asymHip,  unit: '%' },
    { label: 'SI Gối (%)',         imu: imu.siKnee,   cam: cam.siKnee   },
    { label: 'Cadence T (bước/phút)', imu: imu.cadenceL, cam: cam.cadenceL },
    { label: 'Cadence P (bước/phút)', imu: imu.cadenceR, cam: cam.cadenceR },
  ]

  return (
    <div className="bg-white rounded-xl border border-violet-200 shadow-sm p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-violet-700 text-sm uppercase tracking-wide flex items-center gap-2">
          <Camera size={15} /> So sánh Wearable với Phương pháp đo bằng camera
        </h3>
        <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 rounded">
          Đóng ✕
        </button>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Đang tải...</p>}

      {!isLoading && csList.length === 0 && (
        <p className="text-sm text-amber-600 bg-amber-50 rounded-lg p-3">
          Chưa có kết quả đo camera nào liên kết với phiên IMU này. Lưu từ trang <strong>Đo Camera</strong> trước.
        </p>
      )}

      {!isLoading && csList.length > 0 && (
        <>
          {csList.length > 1 && (
            <div className="mb-4">
              <label className="text-xs text-gray-500 mb-1 block">Chọn phiên camera</label>
              <select
                value={selectedCs?.id ?? ''}
                onChange={e => setSelectedCamId(Number(e.target.value))}
                className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-400"
              >
                {csList.map(cs => (
                  <option key={cs.id} value={cs.id}>
                    {dayjs(cs.recorded_at).format('DD/MM/YYYY HH:mm')} · {cs.cameras_used} camera · {cs.frames} frames
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  {['Chỉ số', 'Wearable', 'Camera', 'Chênh lệch', 'Đánh giá'].map(h => (
                    <th key={h} className="pb-2 pr-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(({ label, imu: iv, cam: cv }) => {
                  const agree = agreementBadge(iv, cv)
                  const diff = iv != null && cv != null ? iv - cv : null
                  return (
                    <tr key={label} className="border-b border-gray-50 last:border-0 hover:bg-gray-50">
                      <td className="py-2 pr-3 text-gray-700 font-medium">{label}</td>
                      <td className="py-2 pr-3 text-blue-600 font-mono">
                        {iv != null ? Number(iv).toFixed(1) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="py-2 pr-3 text-violet-600 font-mono">
                        {cv != null ? Number(cv).toFixed(1) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="py-2 pr-3 font-mono text-gray-500">
                        {diff != null ? (diff >= 0 ? '+' : '') + diff.toFixed(1) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="py-2">
                        {agree
                          ? <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${agree.bg} ${agree.color}`}>{agree.label} ({agree.pct.toFixed(1)}%)</span>
                          : <span className="text-gray-300 text-xs">—</span>
                        }
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <p className="text-[11px] text-gray-400 mt-3">
            Chênh lệch = Wearable − Camera · Đánh giá: &lt;10% Tốt · 10–20% Chấp nhận · &gt;20% Khác biệt
          </p>
        </>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AnalysisDetail() {
  const { id } = useParams()
  const { pathname } = useLocation()
  const isAdmin = pathname.startsWith('/admin')
  const backPath = isAdmin ? `/admin/sessions/${id}` : `/sessions/${id}`
  const [showCompare, setShowCompare] = useState(false)
  const queryClient = useQueryClient()

  const reanalyzeMutation = useMutation({
    mutationFn: () => analyzeSession(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analysis', id] })
      queryClient.invalidateQueries({ queryKey: ['chart-rom', id] })
      queryClient.invalidateQueries({ queryKey: ['chart-symmetry', id] })
      queryClient.invalidateQueries({ queryKey: ['chart-gait-cycle', id] })
      queryClient.invalidateQueries({ queryKey: ['chart-phase', id] })
    },
  })

  const { data: camCheckData } = useQuery({
    queryKey: ['camera-sessions-check'],
    queryFn: () => listCameraSessions({ page_size: 1 }),
  })

  useEffect(() => {
    if ((camCheckData?.data?.total ?? 0) > 0) setShowCompare(true)
  }, [camCheckData])

  const { data: sData } = useQuery({ queryKey: ['session', id],    queryFn: () => getSession(id) })
  const { data: aData, isLoading } = useQuery({ queryKey: ['analysis', id],  queryFn: () => getAnalysis(id) })
  const { data: tsData }  = useQuery({ queryKey: ['chart-ts', id],  queryFn: () => getChartTimeseries(id, 3) })
  const { data: romData } = useQuery({ queryKey: ['chart-rom', id], queryFn: () => getChartROM(id) })
  const { data: symData } = useQuery({ queryKey: ['chart-sym', id], queryFn: () => getChartSymmetry(id) })
  const { data: phData }  = useQuery({ queryKey: ['chart-ph', id],  queryFn: () => getChartPhase(id) })
  const { data: gcData }  = useQuery({ queryKey: ['chart-gc', id],  queryFn: () => getChartGaitCycle(id) })

  const session  = sData?.data
  const analysis = aData?.data

  // ── Transform timeseries: {timestamps_ms, series} → [{t, name1, name2...}]
  const timeseries = useMemo(() => {
    const ts = tsData?.data
    if (!ts?.timestamps_ms?.length) return []
    return ts.timestamps_ms.map((t, i) => {
      const row = { t }
      ts.series.forEach(s => { row[s.name] = s.data[i] })
      return row
    })
  }, [tsData])

  const seriesNames = tsData?.data?.series?.map(s => s.name) ?? []

  // ── ROM: {items:[{label,value,unit}]} → [{joint, ROM}]
  const romChart = useMemo(() => {
    return (romData?.data?.items ?? []).map(item => ({
      joint: item.label,
      ROM: item.value,
    }))
  }, [romData])

  // ── Symmetry: {items:[{joint,symmetry_index}]}
  const symItems = symData?.data?.items ?? []

  // ── Phase: {left:{stance_pct,swing_pct}, right:{...}}
  const phase = phData?.data
  const phaseChart = useMemo(() => {
    if (!phase) return []
    return [
      { name: 'Stance T', value: phase.left?.stance_pct ?? 0 },
      { name: 'Swing T',  value: phase.left?.swing_pct  ?? 0 },
      { name: 'Stance P', value: phase.right?.stance_pct ?? 0 },
      { name: 'Swing P',  value: phase.right?.swing_pct  ?? 0 },
    ]
  }, [phase])

  // ── Gait cycle summary
  const gc = gcData?.data

  // ── Chu kỳ dáng đi chuẩn hoá 0–100% (từ timeseries góc khớp)
  const gaitCyclePct = useMemo(() => buildAveragedCycles(timeseries), [timeseries])

  // ── Joint stats for table
  const jointStats = analysis ? [
    { label: 'Hông Trái (Hip L)',      stats: analysis.left_hip_stats,    color: '#dc2626' },
    { label: 'Gối Trái (Knee L)',      stats: analysis.left_knee_stats,   color: '#ea580c' },
    { label: 'Hông Phải (Hip R)',      stats: analysis.right_hip_stats,   color: '#2563eb' },
    { label: 'Gối Phải (Knee R)',      stats: analysis.right_knee_stats,  color: '#7c3aed' },
  ] : []

  if (isLoading) return <div className="p-8 text-gray-400">Đang tải phân tích...</div>

  if (!analysis) return (
    <div className="p-8">
      <div className="flex items-center gap-4 mb-6">
        <Link to={backPath} className="p-2 hover:bg-gray-100 rounded-lg"><ArrowLeft size={20} /></Link>
        <h1 className="text-xl font-bold text-gray-800">Chưa có phân tích</h1>
      </div>
      <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 text-yellow-700 text-sm">
        Phiên đo chưa được phân tích. Dừng thu dữ liệu rồi nhấn <strong>Phân tích</strong> trong trang chi tiết phiên.
      </div>
    </div>
  )

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link to={backPath} className="p-2 hover:bg-gray-100 rounded-lg"><ArrowLeft size={20} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-gray-800">
            Phân tích — <span className="font-mono text-blue-600">{session?.session_code}</span>
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">{phase?.total_samples?.toLocaleString() ?? '—'} mẫu</p>
        </div>
        <button
          onClick={() => reanalyzeMutation.mutate()}
          disabled={reanalyzeMutation.isPending}
          className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          title="Phân tích lại với dữ liệu đã thu"
        >
          <RefreshCw size={14} className={reanalyzeMutation.isPending ? 'animate-spin' : ''} />
          {reanalyzeMutation.isPending ? 'Đang phân tích...' : 'Phân tích lại'}
        </button>
        <button
          onClick={() => setShowCompare(v => !v)}
          className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg border transition-colors ${
            showCompare
              ? 'border-violet-400 bg-violet-50 text-violet-700'
              : 'border-violet-200 text-violet-600 hover:bg-violet-50'
          }`}
        >
          <Camera size={14} /> So sánh Camera
        </button>
      </div>

      {/* Compare panel — shown when toggled */}
      {showCompare && (
        <ComparePanel
          sessionId={Number(id)}
          imuAnalysis={analysis}
          imuGc={gc}
          onClose={() => setShowCompare(false)}
        />
      )}

      {/* Row 1: Reference dataset comparison — đặt trên cùng */}
      <ReferenceSection refEval={analysis.reference_evaluations} />

      {/* Row 2: Score + Remarks + Symmetry */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card title="Điểm đánh giá">
          <ScoreRing score={analysis.gait_score} />
          <ScoreBreakdown breakdown={analysis.score_breakdown} />
        </Card>

        <Card title="Nhận xét">
          {analysis.remarks
            ? <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{analysis.remarks}</p>
            : <p className="text-sm text-gray-400">Không có nhận xét</p>
          }
        </Card>

        <Card title="Chỉ số đối xứng (SI)">
          <div className="space-y-3">
            {symItems.map((item) => (
              <div key={item.joint}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-600">{item.joint}</span>
                  <span className={`font-semibold ${item.symmetry_index < 10 ? 'text-green-600' : item.symmetry_index < 25 ? 'text-amber-600' : 'text-red-600'}`}>
                    {item.symmetry_index != null ? `${Number(item.symmetry_index).toFixed(1)}%` : '—'}
                  </span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all"
                    style={{
                      width: `${Math.min(100, item.symmetry_index ?? 0)}%`,
                      backgroundColor: item.symmetry_index < 10 ? '#10b981' : item.symmetry_index < 25 ? '#f59e0b' : '#ef4444'
                    }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Row 2: Gait cycle summary */}
      {gc && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Số chu kỳ (Trái)',  value: gc.left?.count,               unit: '' },
            { label: 'Nhịp bước (Trái)',  value: gc.left?.cadence_steps_per_min, unit: ' bước/phút' },
            { label: 'Số chu kỳ (Phải)', value: gc.right?.count,              unit: '' },
            { label: 'Nhịp bước (Phải)', value: gc.right?.cadence_steps_per_min, unit: ' bước/phút' },
          ].map(({ label, value, unit }) => (
            <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
              <p className="text-xs text-gray-400 mb-1">{label}</p>
              <p className="text-xl font-bold text-gray-800">
                {value != null ? `${Number(value).toFixed(1)}${unit}` : '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Row 3: Joint stats table */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[
          { title: 'Thông số khớp — Chân Trái', joints: jointStats.slice(0, 2) },
          { title: 'Thông số khớp — Chân Phải', joints: jointStats.slice(2) },
        ].map(({ title, joints }) => (
          <Card key={title} title={title}>
            {joints.map(({ label, stats, color }) => (
              <div key={label} className="mb-3 last:mb-0">
                <p className="text-xs font-semibold mb-1" style={{ color }}>{label}</p>
                <div className="grid grid-cols-4 gap-1 text-center">
                  {[
                    { tag: 'Min', val: stats?.min },
                    { tag: 'Max', val: stats?.max },
                    { tag: 'ROM', val: stats?.rom },
                    { tag: 'Mean', val: stats?.mean },
                  ].map(({ tag, val }) => (
                    <div key={tag} className="bg-gray-50 rounded-lg py-1.5">
                      <p className="text-[10px] text-gray-400">{tag}</p>
                      <p className="text-xs font-bold text-gray-700">{val != null ? `${Number(val).toFixed(1)}°` : '—'}</p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </Card>
        ))}
      </div>

      {/* Row 4: Timeseries (trái) + 1 chu kỳ dáng đi trung bình (phải) */}
      {timeseries.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TimeseriesChart timeseries={timeseries} seriesNames={seriesNames} />
          <GaitCyclePercentChart
            data={gaitCyclePct.data}
            leftCount={gaitCyclePct.leftCount}
            rightCount={gaitCyclePct.rightCount}
            title="Chu Kỳ Dáng Đi (Gait Cycle)"
            footnote="Chu kỳ được tách theo đỉnh gập gối chính (swing) mỗi chân, chuẩn hoá về 0–100% rồi lấy trung bình."
          />
        </div>
      )}

      {/* Row 5: ROM bar + Phase pie */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {romChart.length > 0 && (
          <Card title="Biên độ vận động (ROM)">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={romChart} margin={{ top: 4, right: 16, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="joint" tick={{ fontSize: 10 }} angle={-20} textAnchor="end" />
                <YAxis unit="°" tick={{ fontSize: 11 }} width={40} />
                <Tooltip formatter={(v) => `${Number(v).toFixed(1)}°`} contentStyle={{ fontSize: 11 }} />
                <Bar dataKey="ROM" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                  {romChart.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        )}

        {phaseChart.length > 0 && (
          <Card title="Phân bố pha dáng đi">
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={phaseChart} dataKey="value" nameKey="name"
                  cx="50%" cy="50%" outerRadius={85}
                  label={({ name, value }) => `${name}: ${value}%`} labelLine={false}>
                  {phaseChart.map((_, i) => <Cell key={i} fill={[...COLORS2, '#93c5fd', '#fca5a5'][i % 4]} />)}
                </Pie>
                <Tooltip formatter={(v) => `${v}%`} contentStyle={{ fontSize: 11 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </Card>
        )}
      </div>

      {/* Row 6: IMU Sensor Statistics */}
      {analysis.pelvis_sway_stats && (
        <Card title="Thống kê cảm biến IMU - Gia tốc kế (Accelerometer)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {['x_mediolateral', 'y_anteroposterior', 'z_vertical'].map((axis) => {
              const axisData = analysis.pelvis_sway_stats[axis]
              if (!axisData) return null

              const axisLabels = {
                x_mediolateral: 'X - Trái/Phải',
                y_anteroposterior: 'Y - Trước/Sau',
                z_vertical: 'Z - Lên/Xuống'
              }

              const isPrimary = axis === 'z_vertical'

              return (
                <div key={axis} className={`p-4 rounded-lg border-2 ${isPrimary ? 'border-indigo-200 bg-indigo-50' : 'border-gray-100 bg-gray-50'}`}>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className={`text-sm font-bold ${isPrimary ? 'text-indigo-700' : 'text-gray-700'}`}>
                      {axisLabels[axis]}
                    </h4>
                    {isPrimary && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-600 text-white font-medium">
                        Chính
                      </span>
                    )}
                  </div>
                  <div className="space-y-2">
                    <StatRow label="Mean" value={axisData.mean} unit=" m/s²" color="#6b7280" decimals={4} />
                    <StatRow label="Std Dev" value={axisData.std} unit=" m/s²" color="#6b7280" decimals={4} />
                    <StatRow label="RMS" value={axisData.rms} unit=" m/s²" color={isPrimary ? '#4f46e5' : '#6b7280'} decimals={4} />
                    <StatRow label="Range" value={axisData.range_p2p} unit=" m/s²" color="#6b7280" decimals={4} />
                  </div>
                  <p className="text-[10px] text-gray-400 mt-2">
                    {axisData.n_samples?.toLocaleString()} mẫu
                  </p>
                </div>
              )
            })}
          </div>
          {analysis.pelvis_sway_stats.note && (
            <div className="mt-4 p-3 bg-blue-50 border border-blue-100 rounded-lg">
              <p className="text-xs text-blue-700 leading-relaxed">{analysis.pelvis_sway_stats.note}</p>
            </div>
          )}
        </Card>
      )}

      {/* Row 7: Gyroscope Statistics */}
      {analysis.pelvis_gyro_stats && (
        <Card title="Thống kê cảm biến IMU - Con quay hồi chuyển (Gyroscope)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {['x_roll', 'y_pitch', 'z_yaw'].map((axis) => {
              const axisData = analysis.pelvis_gyro_stats[axis]
              if (!axisData) return null

              const axisLabels = {
                x_roll: 'X - Roll (Nghiêng)',
                y_pitch: 'Y - Pitch (Ngửa/Cúi)',
                z_yaw: 'Z - Yaw (Xoay)'
              }

              const isPrimary = axis === 'y_pitch'

              return (
                <div key={axis} className={`p-4 rounded-lg border-2 ${isPrimary ? 'border-green-200 bg-green-50' : 'border-gray-100 bg-gray-50'}`}>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className={`text-sm font-bold ${isPrimary ? 'text-green-700' : 'text-gray-700'}`}>
                      {axisLabels[axis]}
                    </h4>
                    {isPrimary && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-600 text-white font-medium">
                        Chính
                      </span>
                    )}
                  </div>
                  <div className="space-y-2">
                    <StatRow label="Mean" value={axisData.mean} unit=" deg/s" color="#6b7280" decimals={4} />
                    <StatRow label="Std Dev" value={axisData.std} unit=" deg/s" color="#6b7280" decimals={4} />
                    <StatRow label="RMS" value={axisData.rms} unit=" deg/s" color={isPrimary ? '#16a34a' : '#6b7280'} decimals={4} />
                    <StatRow label="Range" value={axisData.range_p2p} unit=" deg/s" color="#6b7280" decimals={4} />
                  </div>
                  <p className="text-[10px] text-gray-400 mt-2">
                    {axisData.n_samples?.toLocaleString()} mẫu
                  </p>
                </div>
              )
            })}
          </div>
          {analysis.pelvis_gyro_stats.note && (
            <div className="mt-4 p-3 bg-green-50 border border-green-100 rounded-lg">
              <p className="text-xs text-green-700 leading-relaxed">{analysis.pelvis_gyro_stats.note}</p>
            </div>
          )}
        </Card>
      )}

      {/* Row 8: Magnetometer Statistics */}
      {analysis.magn_stats && (
        <Card title="Thống kê cảm biến IMU - Từ trường (Magnetometer)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {['x', 'y', 'z'].map((axis) => {
              const axisData = analysis.magn_stats[axis]
              if (!axisData) return null
              return (
                <div key={axis} className="p-4 rounded-lg border-2 border-amber-100 bg-amber-50">
                  <h4 className="text-sm font-bold text-amber-700 mb-3">Trục {axis.toUpperCase()}</h4>
                  <div className="space-y-2">
                    <StatRow label="Mean" value={axisData.mean} unit=" μT" color="#6b7280" decimals={2} />
                    <StatRow label="Std Dev" value={axisData.std} unit=" μT" color="#6b7280" decimals={2} />
                    <StatRow label="RMS" value={axisData.rms} unit=" μT" color="#b45309" decimals={2} />
                    <StatRow label="Range" value={axisData.range_p2p} unit=" μT" color="#6b7280" decimals={2} />
                  </div>
                  <p className="text-[10px] text-gray-400 mt-2">{axisData.n_samples?.toLocaleString()} mẫu</p>
                </div>
              )
            })}
          </div>
          {analysis.magn_stats.heading && (
            <div className="mt-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
              <h4 className="text-sm font-bold text-amber-800 mb-3">Hướng đi (Heading)</h4>
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center">
                  <p className="text-xs text-gray-500 mb-1">Hướng trung bình</p>
                  <p className="text-xl font-bold text-amber-700">
                    {analysis.magn_stats.heading.mean_deg?.toFixed(1)}°
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-xs text-gray-500 mb-1">Độ lệch chuẩn</p>
                  <p className="text-xl font-bold text-amber-600">
                    {analysis.magn_stats.heading.std_deg?.toFixed(1)}°
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-xs text-gray-500 mb-1">Biên độ</p>
                  <p className="text-xl font-bold text-amber-600">
                    {analysis.magn_stats.heading.range_p2p?.toFixed(1)}°
                  </p>
                </div>
              </div>
              <p className="text-xs text-amber-700 mt-3">
                {analysis.magn_stats.heading.std_deg > 30
                  ? '⚠️ Hướng đi biến động lớn — người dùng có thể đi không thẳng hướng.'
                  : '✓ Hướng đi ổn định.'}
              </p>
            </div>
          )}
          {analysis.magn_stats.note && (
            <div className="mt-4 p-3 bg-amber-50 border border-amber-100 rounded-lg">
              <p className="text-xs text-amber-800 leading-relaxed">{analysis.magn_stats.note}</p>
            </div>
          )}
        </Card>
      )}

      {/* Row 9: FSR Force Analysis — tạm ẩn, FSR chỉ dùng để xác định chu kỳ chạm/nhấc chân, không cần phân tích lực */}
      {false && analysis.fsr_stats && (
        <Card title="Phân tích lực FSR — Mũi chân & Gót chân">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            {['left', 'right'].map((side) => {
              const foot = analysis.fsr_stats[side]
              if (!foot) return null
              const isLeft = side === 'left'
              const borderCls = isLeft ? 'border-blue-200 bg-blue-50' : 'border-violet-200 bg-violet-50'
              const titleCls  = isLeft ? 'text-blue-700' : 'text-violet-700'
              const accentCls = isLeft ? 'bg-blue-600'  : 'bg-violet-600'
              return (
                <div key={side} className={`p-4 rounded-lg border-2 ${borderCls}`}>
                  <div className="flex items-center justify-between mb-3">
                    <h4 className={`text-sm font-bold ${titleCls}`}>
                      {isLeft ? 'Chân Trái' : 'Chân Phải'}
                    </h4>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full text-white font-medium ${accentCls}`}>
                      {foot.heel?.n_strikes ?? 0} heel strikes
                    </span>
                  </div>

                  <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Gót chân (Heel — FSR2)</p>
                  <div className="space-y-1 mb-3">
                    <StatRow label="Peak lực trung bình" value={foot.heel?.peak_mean} unit=" ADC" color="#6b7280" decimals={1} />
                    <StatRow label="Peak lực tối đa"     value={foot.heel?.peak_max}  unit=" ADC" color="#dc2626" decimals={1} />
                    <StatRow label="Độ lệch chuẩn"       value={foot.heel?.peak_std}  unit=" ADC" color="#6b7280" decimals={1} />
                  </div>

                  <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Mũi chân (Toe — FSR1)</p>
                  <div className="space-y-1 mb-3">
                    <StatRow label="Peak lực trung bình" value={foot.toe?.peak_mean} unit=" ADC" color="#6b7280" decimals={1} />
                    <StatRow label="Peak lực tối đa"     value={foot.toe?.peak_max}  unit=" ADC" color="#dc2626" decimals={1} />
                    <StatRow label="Độ lệch chuẩn"       value={foot.toe?.peak_std}  unit=" ADC" color="#6b7280" decimals={1} />
                  </div>

                  <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Tốc độ tăng tải (Loading Rate)</p>
                  <div className="space-y-1">
                    <StatRow label="Loading rate (mean)" value={foot.loading_rate?.mean} unit=" ADC/ms" color="#7c3aed" decimals={2} />
                    <StatRow label="Loading rate (std)"  value={foot.loading_rate?.std}  unit=" ADC/ms" color="#6b7280" decimals={2} />
                  </div>
                </div>
              )
            })}
          </div>

          {/* FSR Symmetry */}
          {analysis.fsr_stats.symmetry && (
            <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">
                Chỉ số đối xứng lực (Force Symmetry Index)
              </p>
              <div className="grid grid-cols-2 gap-4">
                {[
                  { label: 'SI Gót chân (Heel)',  value: analysis.fsr_stats.symmetry.heel_si },
                  { label: 'SI Mũi chân (Toe)',   value: analysis.fsr_stats.symmetry.toe_si  },
                ].map(({ label, value }) => {
                  const v = value ?? null
                  const color = v == null ? '#9ca3af' : v < 10 ? '#16a34a' : v < 25 ? '#d97706' : '#dc2626'
                  const badge = v == null ? 'Không có dữ liệu' : v < 10 ? 'Đối xứng tốt' : v < 25 ? 'Hơi mất đối xứng' : 'Mất đối xứng'
                  return (
                    <div key={label} className="text-center">
                      <p className="text-xs text-gray-500 mb-1">{label}</p>
                      <p className="text-2xl font-bold" style={{ color }}>
                        {v != null ? `${v.toFixed(1)}%` : '—'}
                      </p>
                      <p className="text-[11px] font-semibold mt-1" style={{ color }}>{badge}</p>
                    </div>
                  )
                })}
              </div>
              <p className="text-[10px] text-gray-400 mt-3 text-center">
                SI = 2×|L−R| / (|L|+|R|) × 100 · SI &lt;10%: đối xứng · 10–25%: cần theo dõi · &gt;25%: bất thường
              </p>
            </div>
          )}

          <div className="mt-4 p-3 bg-blue-50 border border-blue-100 rounded-lg">
            <p className="text-xs text-blue-700 leading-relaxed">
              <strong>Lưu ý:</strong> Giá trị FSR là raw ADC (0–1023). Gót chân (FSR2) dùng để phát hiện heel strike;
              Mũi chân (FSR1) dùng để phát hiện toe-off. Loading rate cao chỉ ra tải trọng tác động nhanh khi tiếp đất.
            </p>
          </div>
        </Card>
      )}

      {/* Row 10: Double Support Analysis — tạm ẩn khỏi bảng phân tích, chưa xoá */}
      {false && analysis.double_support && (
        <Card title="Phân tích chống đỡ 2 chân (Double Support)">
          {(() => {
            const ds = analysis.double_support
            const pct = ds.ratio_pct ?? (ds.ratio != null ? ds.ratio * 100 : null)
            const isNormal = pct != null && pct >= 18 && pct <= 28
            const isHigh   = pct != null && pct > 28
            const statusColor = pct == null ? '#9ca3af' : isNormal ? '#16a34a' : isHigh ? '#dc2626' : '#d97706'
            const statusLabel = pct == null ? '—' : isNormal ? 'Bình thường' : isHigh ? 'Cao — có thể do thăng bằng kém' : 'Thấp — thận trọng'
            const statusBg    = pct == null ? 'bg-gray-50 border-gray-200' : isNormal ? 'bg-green-50 border-green-200' : isHigh ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'
            return (
              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { label: 'Tỉ lệ (%)', value: pct?.toFixed(1), unit: '%', note: 'Chuẩn: 18–28%' },
                    { label: 'Số lần',    value: ds.n_bouts,       unit: 'lần', note: 'Số chuỗi DS' },
                    { label: 'Thời gian TB', value: ds.avg_duration_ms?.toFixed(0), unit: ' ms', note: 'Mỗi đợt DS' },
                    { label: 'Tỉ lệ (raw)', value: ds.ratio?.toFixed(3), unit: '', note: '0.0 – 1.0' },
                  ].map(({ label, value, unit, note }) => (
                    <div key={label} className="bg-white rounded-lg border border-gray-100 shadow-sm p-3 text-center">
                      <p className="text-[10px] text-gray-400 mb-0.5">{label}</p>
                      <p className="text-xl font-bold text-gray-800">
                        {value != null ? `${value}${unit}` : '—'}
                      </p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{note}</p>
                    </div>
                  ))}
                </div>

                <div className={`p-4 rounded-lg border-2 ${statusBg}`}>
                  <div className="flex items-center gap-3">
                    <div>
                      <p className="text-sm font-semibold" style={{ color: statusColor }}>
                        Đánh giá: {statusLabel}
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        Double support là giai đoạn cả hai chân đồng thời tiếp đất — chỉ số này phản ánh tính ổn định
                        và nhịp điệu bước đi. Người cao tuổi hoặc có vấn đề thăng bằng thường có DS cao hơn.
                      </p>
                    </div>
                    {pct != null && (
                      <div className="shrink-0">
                        <div className="relative w-16 h-16">
                          <svg viewBox="0 0 60 60" className="w-full h-full -rotate-90">
                            <circle cx="30" cy="30" r="24" fill="none" stroke="#f3f4f6" strokeWidth="6" />
                            <circle cx="30" cy="30" r="24" fill="none" stroke={statusColor} strokeWidth="6"
                              strokeDasharray={`${Math.min(pct, 100) * 1.507} 150.7`} strokeLinecap="round" />
                          </svg>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <span className="text-xs font-bold" style={{ color: statusColor }}>{pct.toFixed(0)}%</span>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <p className="text-[11px] text-gray-400">
                  Tham chiếu lâm sàng: người đi bình thường DS ≈ 18–28% chu kỳ dáng đi.
                  DS &gt;30% có thể liên quan đến giảm tốc độ, mất thăng bằng, hoặc đau khớp.
                </p>
              </div>
            )
          })()}
        </Card>
      )}

      {/* Row 11: Force Evaluation from accelerometer — tạm ẩn, không cần phân tích lực */}
      {false && analysis.pelvis_sway_stats && (
        <Card title="Đánh giá lực tác động (Force Evaluation)">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {(() => {
              const zData = analysis.pelvis_sway_stats.z_vertical
              const yData = analysis.pelvis_sway_stats.y_anteroposterior
              const xData = analysis.pelvis_sway_stats.x_mediolateral

              const forceMetrics = [
                {
                  label: 'Lực tác động dọc (Vertical)',
                  description: 'Lực theo phương thẳng đứng khi chạm đất',
                  rms: zData?.rms,
                  range: zData?.range_p2p,
                  color: '#dc2626',
                  isPrimary: true
                },
                {
                  label: 'Lực đẩy trước/sau (AP)',
                  description: 'Lực đẩy theo hướng trước-sau',
                  rms: yData?.rms,
                  range: yData?.range_p2p,
                  color: '#ea580c',
                  isPrimary: false
                },
                {
                  label: 'Lực ngang (ML)',
                  description: 'Lực theo phương ngang trái-phải',
                  rms: xData?.rms,
                  range: xData?.range_p2p,
                  color: '#f59e0b',
                  isPrimary: false
                }
              ]

              return forceMetrics.map((metric) => (
                <div key={metric.label} className={`p-4 rounded-lg border-2 ${metric.isPrimary ? 'border-red-200 bg-red-50' : 'border-gray-100 bg-gray-50'}`}>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className={`text-sm font-bold ${metric.isPrimary ? 'text-red-700' : 'text-gray-700'}`}>
                      {metric.label}
                    </h4>
                    {metric.isPrimary && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-600 text-white font-medium">
                        Chính
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-gray-500 mb-3">{metric.description}</p>
                  <div className="space-y-2">
                    <StatRow label="RMS (Lực động)" value={metric.rms} unit=" m/s²" color={metric.color} decimals={4} />
                    <StatRow label="Biên độ (Peak-to-Peak)" value={metric.range} unit=" m/s²" color="#6b7280" decimals={4} />
                  </div>
                  {metric.rms != null && (
                    <div className="mt-3 pt-2 border-t border-gray-200">
                      <p className="text-[10px] text-gray-500">
                        Đánh giá: {
                          metric.rms < 1.5 ? (
                            <span className="text-green-600 font-semibold">Bình thường</span>
                          ) : metric.rms < 2.5 ? (
                            <span className="text-amber-600 font-semibold">Trung bình</span>
                          ) : (
                            <span className="text-red-600 font-semibold">Cao</span>
                          )
                        }
                      </p>
                    </div>
                  )}
                </div>
              ))
            })()}
          </div>
          <div className="mt-4 p-3 bg-amber-50 border border-amber-100 rounded-lg">
            <p className="text-xs text-amber-800 leading-relaxed">
              <strong>Lưu ý:</strong> Đánh giá lực được ước tính từ dữ liệu gia tốc kế (RMS).
              Lực tác động dọc (vertical) phản ánh cường độ va chạm khi bàn chân chạm đất.
              RMS cao có thể chỉ ra tác động mạnh hoặc kỹ thuật đi không tối ưu.
            </p>
          </div>
        </Card>
      )}
    </div>
  )
}
