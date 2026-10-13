export default function ScoreRing({ score, label = 'Điểm dáng đi' }) {
  const s = Math.round(score ?? 0)
  const color = s >= 80 ? '#10b981' : s >= 60 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex flex-col items-center">
      <div className="relative w-32 h-32">
        <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
          <circle cx="60" cy="60" r="50" fill="none" stroke="#f3f4f6" strokeWidth="12" />
          <circle cx="60" cy="60" r="50" fill="none" stroke={color} strokeWidth="12"
            strokeDasharray={`${s * 3.14} 314`} strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold" style={{ color }}>{s}</span>
          <span className="text-xs text-gray-400">/ 100</span>
        </div>
      </div>
      <p className="mt-2 text-sm text-gray-500">{label}</p>
    </div>
  )
}
