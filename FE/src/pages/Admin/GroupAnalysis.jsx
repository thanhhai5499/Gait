import { useMemo, useState } from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import Card from '../../components/ui/Card'
import ScoreRing from '../../components/Analysis/ScoreRing'
import ReferenceSection, { SummaryBadges } from '../../components/Analysis/ReferenceSection'
import GaitCyclePercentChart from '../../components/Charts/GaitCyclePercentChart'
import { getGroupAnalysis } from '../../api/groupAnalysis'
import { getChartTimeseries } from '../../api/sessions'
import { buildAveragedCycles, averageMemberCycles } from '../../utils/gaitCycle'

const AGE_BUCKETS = [
  { label: 'Dưới 18',  min: 0,   max: 17 },
  { label: '18–30',    min: 18,  max: 30 },
  { label: '31–45',    min: 31,  max: 45 },
  { label: '46–60',    min: 46,  max: 60 },
  { label: '61–75',    min: 61,  max: 75 },
  { label: '76+',      min: 76,  max: 130 },
]

const SEX_OPTIONS = [
  { value: '',       label: 'Tất cả' },
  { value: 'male',   label: 'Nam' },
  { value: 'female', label: 'Nữ' },
]

function sexLabel(sex) {
  return sex === 'male' ? 'Nam' : sex === 'female' ? 'Nữ' : 'Tất cả'
}

/** "Nam, 18–30 tuổi" — mô tả nhóm đang xem, dùng từ filters do backend trả về. */
function groupDescription(filters) {
  if (!filters) return ''
  return `${sexLabel(filters.sex)}, ${filters.age_min}–${filters.age_max} tuổi`
}

function GroupGaitCycleChart({ members, groupLabel }) {
  const results = useQueries({
    queries: members.map((m) => ({
      queryKey: ['chart-ts', m.session_id],
      queryFn: () => getChartTimeseries(m.session_id, 3),
      enabled: !!m.session_id,
    })),
  })

  const loading = results.some(r => r.isLoading)

  const { data, leftCount, rightCount } = useMemo(() => {
    const memberCycles = results
      .filter(r => r.data?.data)
      .map((r) => {
        const ts = r.data.data
        if (!ts?.timestamps_ms?.length) return null
        const rows = ts.timestamps_ms.map((t, i) => {
          const row = { t }
          ts.series.forEach(s => { row[s.name] = s.data[i] })
          return row
        })
        return buildAveragedCycles(rows)
      })
    return averageMemberCycles(memberCycles)
  }, [results])

  const title = `Chu Kỳ Dáng Đi (Gait Cycle) — Trung bình nhóm (${groupLabel})`

  if (loading) {
    return (
      <Card title={title}>
        <p className="text-sm text-gray-400">Đang tải dữ liệu chu kỳ dáng đi của từng thành viên...</p>
      </Card>
    )
  }

  return (
    <GaitCyclePercentChart
      data={data}
      leftCount={leftCount}
      rightCount={rightCount}
      title={title}
      footnote="Mỗi thành viên đóng góp 1 chu kỳ trung bình (từ phiên đo mới nhất); biểu đồ là trung bình các chu kỳ đó theo % chu kỳ dáng đi."
    />
  )
}

function RomTable({ romAvg, groupLabel }) {
  const rows = [
    { label: 'Hông Trái (Hip L)',  stats: romAvg?.left_hip,   color: '#dc2626' },
    { label: 'Gối Trái (Knee L)',  stats: romAvg?.left_knee,  color: '#ea580c' },
    { label: 'Hông Phải (Hip R)',  stats: romAvg?.right_hip,  color: '#2563eb' },
    { label: 'Gối Phải (Knee R)',  stats: romAvg?.right_knee, color: '#7c3aed' },
  ]
  return (
    <Card title={`Biên độ vận động trung bình (ROM) — ${groupLabel}`}>
      {rows.map(({ label, stats, color }) => (
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
  )
}

function SymmetryCard({ symmetryAvg }) {
  const items = [
    { joint: 'Hông (Hip)', value: symmetryAvg?.hip },
    { joint: 'Gối (Knee)', value: symmetryAvg?.knee },
  ]
  return (
    <Card title="Chỉ số đối xứng trung bình (SI)">
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.joint}>
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-600">{item.joint}</span>
              <span className={`font-semibold ${item.value < 10 ? 'text-green-600' : item.value < 25 ? 'text-amber-600' : 'text-red-600'}`}>
                {item.value != null ? `${Number(item.value).toFixed(1)}%` : '—'}
              </span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(100, item.value ?? 0)}%`,
                  backgroundColor: item.value < 10 ? '#10b981' : item.value < 25 ? '#f59e0b' : '#ef4444',
                }} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function GaitCycleStatsCard({ gaitCycleAvg }) {
  const items = [
    { label: 'Số chu kỳ TB (Trái)', value: gaitCycleAvg?.left?.count,               unit: '' },
    { label: 'Nhịp bước TB (Trái)', value: gaitCycleAvg?.left?.cadence_steps_per_min, unit: ' bước/phút' },
    { label: 'Số chu kỳ TB (Phải)', value: gaitCycleAvg?.right?.count,              unit: '' },
    { label: 'Nhịp bước TB (Phải)', value: gaitCycleAvg?.right?.cadence_steps_per_min, unit: ' bước/phút' },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {items.map(({ label, value, unit }) => (
        <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p className="text-xs text-gray-400 mb-1">{label}</p>
          <p className="text-xl font-bold text-gray-800">
            {value != null ? `${Number(value).toFixed(1)}${unit}` : '—'}
          </p>
        </div>
      ))}
    </div>
  )
}

function MembersTable({ members }) {
  return (
    <Card title={`Thành viên nhóm (${members.length})`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              {['Họ tên', 'Tuổi', 'Giới tính', 'Mã phiên đo', 'Điểm dáng đi'].map(h => (
                <th key={h} className="pb-2 pr-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50">
                <td className="py-2 pr-3 text-gray-700 font-medium">{m.full_name}</td>
                <td className="py-2 pr-3 text-gray-500">{m.age}</td>
                <td className="py-2 pr-3 text-gray-500">{m.sex === 'male' ? 'Nam' : 'Nữ'}</td>
                <td className="py-2 pr-3 font-mono text-blue-600">{m.session_code}</td>
                <td className="py-2 pr-3 font-semibold text-gray-700">{m.gait_score != null ? Math.round(m.gait_score) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function GroupAnalysis() {
  const [sex, setSex] = useState('')
  const [bucketIdx, setBucketIdx] = useState(1)
  const [query, setQuery] = useState(null)

  const bucket = AGE_BUCKETS[bucketIdx]

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['group-analysis', query],
    queryFn: () => getGroupAnalysis(query),
    enabled: !!query,
  })

  const result = data?.data
  const groupLabel = groupDescription(result?.filters)

  const handleAnalyze = () => {
    setQuery({ sex, ageMin: bucket.min, ageMax: bucket.max })
  }

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <Users size={22} className="text-purple-600" />
        <h1 className="text-xl font-bold text-gray-800">Phân tích nhóm</h1>
        {result && result.member_count > 0 && (
          <span className="px-3 py-1 rounded-full text-sm font-semibold bg-purple-100 text-purple-700">
            Nhóm: {groupLabel} · {result.member_count} thành viên
          </span>
        )}
      </div>

      {/* Filter form */}
      <Card title="Bộ lọc nhóm">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Giới tính</label>
            <select value={sex} onChange={(e) => setSex(e.target.value)}
              className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-purple-400">
              {SEX_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Khoảng tuổi</label>
            <select value={bucketIdx} onChange={(e) => setBucketIdx(Number(e.target.value))}
              className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-purple-400">
              {AGE_BUCKETS.map((b, i) => <option key={b.label} value={i}>{b.label} tuổi</option>)}
            </select>
          </div>
          <button
            onClick={handleAnalyze}
            disabled={isFetching}
            className="px-4 py-1.5 text-sm font-semibold rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {isFetching ? 'Đang phân tích...' : 'Phân tích nhóm'}
          </button>
        </div>
      </Card>

      {isLoading && <p className="text-sm text-gray-400">Đang tải...</p>}

      {result && result.member_count === 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-amber-700 text-sm">
          Không có thành viên nào phù hợp bộ lọc (giới tính: {sex ? (sex === 'male' ? 'Nam' : 'Nữ') : 'Tất cả'},
          tuổi {bucket.min}–{bucket.max}) có phiên đo đã phân tích.
        </div>
      )}

      {result && result.member_count > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card title="Điểm dáng đi trung bình">
              <ScoreRing score={result.avg_gait_score} label={`Trung bình ${result.member_count} thành viên`} />
            </Card>
            <Card title="Tổng quan nhóm">
              <p className="text-sm text-gray-600">
                Giới tính: <strong>{sex ? (sex === 'male' ? 'Nam' : 'Nữ') : 'Tất cả'}</strong><br />
                Khoảng tuổi: <strong>{bucket.min}–{bucket.max}</strong><br />
                Số thành viên: <strong>{result.member_count}</strong>
              </p>
              {result.reference_evaluations?.summary && (
                <div className="mt-3">
                  <SummaryBadges summary={result.reference_evaluations.summary} />
                </div>
              )}
            </Card>
            <SymmetryCard symmetryAvg={result.symmetry_avg} />
          </div>

          <GaitCycleStatsCard gaitCycleAvg={result.gait_cycle_avg} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <RomTable romAvg={result.rom_avg} groupLabel={groupLabel} />
            <GroupGaitCycleChart members={result.members} groupLabel={groupLabel} />
          </div>

          <ReferenceSection
            refEval={result.reference_evaluations}
            title={`So sánh nhóm với Dataset Chuẩn (NTU · Yishun · Chinese) — ${groupLabel}`}
          />

          <MembersTable members={result.members} />
        </>
      )}
    </div>
  )
}
