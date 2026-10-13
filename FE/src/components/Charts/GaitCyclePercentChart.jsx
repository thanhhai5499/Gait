import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import Card from '../ui/Card'
import { seriesLabel, seriesColor } from '../../utils/jointSeries'

const NAMES = ['Left Hip', 'Left Knee', 'Right Hip', 'Right Knee']

export default function GaitCyclePercentChart({ data, leftCount, rightCount, title, footnote }) {
  const [hidden, setHidden] = useState({})
  const toggle = (name) => setHidden((p) => ({ ...p, [name]: !p[name] }))

  if (!leftCount && !rightCount) {
    return (
      <Card title={title}>
        <p className="text-sm text-gray-400">Không đủ dữ liệu để tách chu kỳ dáng đi.</p>
      </Card>
    )
  }

  return (
    <Card title={title}>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5 mb-3">
        {NAMES.map((name, i) => (
          <button key={name} onClick={() => toggle(name)}
            className={`flex items-center gap-1.5 text-xs transition-opacity ${hidden[name] ? 'opacity-25' : 'opacity-100'}`}>
            <svg width="22" height="10">
              <line x1="0" y1="5" x2="22" y2="5" stroke={seriesColor(name, i)} strokeWidth="2.5" />
            </svg>
            <span className="font-medium" style={{ color: seriesColor(name, i) }}>{seriesLabel(name)}</span>
          </button>
        ))}
        <span className="text-[10px] text-gray-400 self-center ml-auto italic">
          {leftCount} chu kỳ (Trái) · {rightCount} chu kỳ (Phải)
        </span>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="pct" type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} />
          <YAxis unit="°" tick={{ fontSize: 11 }} width={40} />
          <Tooltip
            formatter={(v, name) => [v != null ? `${Number(v).toFixed(1)}°` : '—', seriesLabel(name)]}
            labelFormatter={(v) => `${v}% chu kỳ`}
            contentStyle={{ fontSize: 11 }}
          />
          {NAMES.map((name, i) => (
            <Line key={name} type="monotone" dataKey={name}
              stroke={seriesColor(name, i)} strokeWidth={2}
              dot={false} isAnimationActive={false}
              hide={!!hidden[name]} connectNulls />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {footnote && <p className="text-[10px] text-gray-400 mt-2">{footnote}</p>}
    </Card>
  )
}
