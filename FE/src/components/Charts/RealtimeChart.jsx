import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'

// WS broadcasts SensorReadingIn fields: left_hip, left_knee, right_hip, right_knee.
// Thiết bị không có cảm biến cổ chân nên không có kênh ankle.
const JOINTS = [
  { key: 'left_hip',    name: 'Hông T',     color: '#3b82f6' },
  { key: 'left_knee',   name: 'Gối T',      color: '#10b981' },
  { key: 'right_hip',   name: 'Hông P',     color: '#f59e0b' },
  { key: 'right_knee',  name: 'Gối P',      color: '#ef4444' },
]

export default function RealtimeChart({ readings }) {
  const data = useMemo(() =>
    readings.map((r) => ({
      t: r.timestamp_ms,
      left_hip:    r.left_hip,
      left_knee:   r.left_knee,
      right_hip:   r.right_hip,
      right_knee:  r.right_knee,
    })),
    [readings]
  )

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        Chờ dữ liệu từ cảm biến...
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="t"
          tickFormatter={(v) => `${(v / 1000).toFixed(1)}s`}
          tick={{ fontSize: 11 }}
          interval="preserveStartEnd"
        />
        <YAxis
          unit="°"
          domain={['auto', 'auto']}
          tick={{ fontSize: 11 }}
          width={40}
        />
        <Tooltip
          formatter={(v, name) => [`${Number(v).toFixed(1)}°`, name]}
          labelFormatter={(v) => `t=${(v / 1000).toFixed(2)}s`}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {JOINTS.map(({ key, name, color }) => (
          <Line
            key={key}
            type="monotone"
            dataKey={key}
            name={name}
            stroke={color}
            dot={false}
            strokeWidth={1.5}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
