import Card from '../ui/Card'

export const BAND_CFG = {
  normal:      { label: 'Bình thường',  color: 'text-green-600',  bg: 'bg-green-100',  dot: 'bg-green-500' },
  borderline:  { label: 'Cận ngưỡng',  color: 'text-amber-600',  bg: 'bg-amber-100',  dot: 'bg-amber-500' },
  abnormal:    { label: 'Bất thường',  color: 'text-red-600',    bg: 'bg-red-100',    dot: 'bg-red-500'   },
  unavailable: { label: 'Không có dữ liệu', color: 'text-gray-400', bg: 'bg-gray-100', dot: 'bg-gray-400' },
}

export const DATASET_LABEL = { ntu: 'NTU 2026', yishun: 'Yishun 2020', chinese: 'Chinese 2023', none: '—' }

export const PARAM_LABEL = {
  // Kinematics
  knee_peak_flexion_deg: 'Gối – Gập tối đa (Flexion max)',
  knee_peak_ext_deg:     'Gối – Duỗi tối đa (Extension max)',
  knee_stance_min_deg:   'Gối – Min giai đoạn chống',
  knee_rom_deg:          'Gối – Biên độ (ROM)',
  hip_peak_flexion_deg:  'Hông – Gập tối đa (Flexion max)',
  hip_peak_ext_deg:      'Hông – Duỗi tối đa (Extension max)',
  hip_stance_min_deg:    'Hông – Min giai đoạn chống',
  hip_rom_deg:           'Hông – Biên độ (ROM)',
  // Spatiotemporal
  gait_speed:            'Tốc độ đi',
  cadence:               'Nhịp bước',
  step_length:           'Độ dài bước (Step length)',
  stride_length:         'Stride length',
  stride_width:          'Stride width',
  stance_pct:            'Tỉ lệ chống (%)',
  double_support_time:   'Thời gian chống 2 chân',
  single_support_time:   'Thời gian chống 1 chân',
  cycle_time:            'Thời gian 1 chu kỳ',
}

const SEVERITY_CFG = {
  abnormal:   { icon: '⛔', color: 'text-red-700',   bg: 'bg-red-50   border-red-200'   },
  borderline: { icon: '⚠️', color: 'text-amber-700', bg: 'bg-amber-50 border-amber-200' },
}

function ZBar({ z }) {
  if (z == null) return <span className="text-gray-300 text-xs">—</span>
  const clamped = Math.min(Math.max(z, -4), 4)
  const pct = ((clamped + 4) / 8) * 100
  const color = Math.abs(z) < 1 ? '#10b981' : Math.abs(z) < 2 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex items-center gap-2">
      <div className="relative w-24 h-2 bg-gray-100 rounded-full overflow-visible">
        {/* centre line */}
        <div className="absolute top-0 left-1/2 w-px h-2 bg-gray-300" />
        <div className="absolute top-0 h-2 w-1.5 rounded-full -translate-x-1/2 -translate-y-0"
          style={{ left: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs font-mono font-semibold" style={{ color }}>
        {z >= 0 ? '+' : ''}{z.toFixed(2)}
      </span>
    </div>
  )
}

function EvalRow({ ev }) {
  const band = BAND_CFG[ev.band] ?? BAND_CFG.unavailable
  const label = PARAM_LABEL[ev.parameter] ?? ev.parameter
  return (
    <tr className="border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors">
      <td className="py-2 pr-3 text-sm text-gray-700 font-medium">{label}</td>
      <td className="py-2 pr-3 text-sm text-gray-500 font-mono text-right">
        {ev.measured != null ? Number(ev.measured).toFixed(2) : '—'}
        <span className="text-gray-300 ml-1">{ev.unit}</span>
      </td>
      <td className="py-2 pr-3 text-sm text-gray-400 font-mono text-right">
        {ev.mean != null ? `${Number(ev.mean).toFixed(2)} ± ${Number(ev.sd).toFixed(2)}` : '—'}
      </td>
      <td className="py-2 pr-3"><ZBar z={ev.z} /></td>
      <td className="py-2 pr-3">
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${band.bg} ${band.color}`}>
          {band.label}
        </span>
      </td>
      <td className="py-2 text-[11px] text-gray-400">{DATASET_LABEL[ev.dataset] ?? ev.dataset}</td>
    </tr>
  )
}

export function SummaryBadges({ summary }) {
  const items = [
    { key: 'normal',     label: 'Bình thường' },
    { key: 'borderline', label: 'Cận ngưỡng' },
    { key: 'abnormal',   label: 'Bất thường' },
  ]
  return (
    <div className="flex gap-3 flex-wrap">
      {items.map(({ key, label }) => {
        const cfg = BAND_CFG[key]
        return (
          <div key={key} className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-semibold ${cfg.bg} ${cfg.color}`}>
            <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
            {summary[key] ?? 0} {label}
          </div>
        )
      })}
    </div>
  )
}

function SIRow({ ev }) {
  const band = BAND_CFG[ev.band] ?? BAND_CFG.unavailable
  return (
    <div className="flex items-start justify-between gap-3 py-2 border-b border-gray-50 last:border-0">
      <div className="flex-1">
        <p className="text-sm font-medium text-gray-700">{ev.label}</p>
        <p className="text-[11px] text-gray-400 mt-0.5">{ev.threshold}</p>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-sm font-mono font-semibold text-gray-700">
          {ev.measured != null ? `${Number(ev.measured).toFixed(1)}%` : '—'}
        </span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${band.bg} ${band.color}`}>
          {band.label}
        </span>
      </div>
    </div>
  )
}

export default function ReferenceSection({ refEval, title = 'So sánh với Dataset Chuẩn (NTU · Yishun · Chinese)' }) {
  if (!refEval) return null
  const {
    kinematic = [],
    spatiotemporal = [],
    symmetry = [],
    clinical_notes = [],
    summary = {},
    patient,
  } = refEval
  const allEmpty = kinematic.length === 0 && spatiotemporal.length === 0

  const tableHead = (
    <thead>
      <tr className="border-b border-gray-200">
        {['Thông số', 'Đo được', 'Chuẩn (mean ± SD)', 'Z-score', 'Phân loại', 'Dataset'].map(h => (
          <th key={h} className="pb-2 pr-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">{h}</th>
        ))}
      </tr>
    </thead>
  )

  return (
    <Card title={title}>
      {/* Patient info + summary badges */}
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        {patient && (
          <p className="text-xs text-gray-400">
            Tham chiếu cho: <strong>{patient.sex === 'men' ? 'Nam' : 'Nữ'}</strong>, {patient.age} tuổi
          </p>
        )}
        <SummaryBadges summary={summary} />
      </div>

      {/* Clinical notes — hiển thị trước bảng số liệu */}
      {clinical_notes.length > 0 && (
        <div className="mb-5 space-y-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Nhận xét lâm sàng</p>
          {clinical_notes.map((n, i) => {
            const cfg = SEVERITY_CFG[n.severity] ?? SEVERITY_CFG.borderline
            return (
              <div key={i} className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-sm ${cfg.bg} ${cfg.color}`}>
                <span className="shrink-0">{cfg.icon}</span>
                <span>{n.note}</span>
              </div>
            )
          })}
        </div>
      )}

      {allEmpty ? (
        <p className="text-sm text-gray-400">Không đủ dữ liệu để đánh giá.</p>
      ) : (
        <div className="space-y-6">
          {/* Kinematics */}
          {kinematic.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide mb-2">
                Động học khớp (Kinematics) — NTU Dataset 2026
              </p>
              <div className="overflow-x-auto">
                <table className="w-full">
                  {tableHead}
                  <tbody>{kinematic.map((ev, i) => <EvalRow key={i} ev={ev} />)}</tbody>
                </table>
              </div>
            </div>
          )}

          {/* Spatiotemporal */}
          {spatiotemporal.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-2">
                Thời gian – Không gian (Spatiotemporal) — Yishun 2020 / Chinese 2023
              </p>
              <div className="overflow-x-auto">
                <table className="w-full">
                  {tableHead}
                  <tbody>{spatiotemporal.map((ev, i) => <EvalRow key={i} ev={ev} />)}</tbody>
                </table>
              </div>
            </div>
          )}

          {/* Symmetry Index */}
          {symmetry.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-violet-600 uppercase tracking-wide mb-2">
                Chỉ số đối xứng (Symmetry Index) — Ngưỡng lâm sàng
              </p>
              <div className="divide-y divide-gray-50">
                {symmetry.map((ev, i) => <SIRow key={i} ev={ev} />)}
              </div>
              <p className="text-[11px] text-gray-400 mt-2">
                AI = |Trái − Phải| / ((Trái + Phải) / 2) × 100 · AI &gt; 10% cần chú ý lâm sàng (Section 5.2)
              </p>
            </div>
          )}
        </div>
      )}

      <div className="mt-5 p-3 bg-blue-50 border border-blue-100 rounded-lg text-xs text-blue-700 leading-relaxed">
        <strong>Ngưỡng Z-score (Mục 5.2):</strong>{' '}
        |Z| &lt; 1,0 → Bình thường · 1,0 ≤ |Z| &lt; 2,0 → Cận ngưỡng · |Z| ≥ 2,0 → Bất thường.{' '}
        Tham chiếu: Yishun Study (IF 3,7 · ĐNA · 21–90 tuổi) · NTU Dataset (IF 6,9 · ĐNA · 50–80 tuổi) · SV Trung Quốc (PMC).
      </div>
    </Card>
  )
}
