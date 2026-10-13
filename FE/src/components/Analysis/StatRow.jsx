export default function StatRow({ label, value, unit = '°', color, decimals = 1 }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm font-semibold" style={{ color }}>{value != null ? `${Number(value).toFixed(decimals)}${unit}` : '—'}</span>
    </div>
  )
}
