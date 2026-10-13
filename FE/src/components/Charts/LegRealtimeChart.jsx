import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
  AreaChart, Area,
} from 'recharts'

// Arduino gửi: left_hip, left_knee, right_hip, right_knee (không có ankle)
const JOINT_CONFIG = {
  left: [
    { key: 'left_hip',  name: 'Hông (Hip)',  color: '#6b7280', strokeWidth: 2 },
    { key: 'left_knee', name: 'Gối (Knee)',  color: '#ef4444', strokeWidth: 2.5 },
  ],
  right: [
    { key: 'right_hip',  name: 'Hông (Hip)', color: '#6b7280', strokeWidth: 2 },
    { key: 'right_knee', name: 'Gối (Knee)', color: '#ef4444', strokeWidth: 2.5 },
  ],
}

const FORCE_CONFIG = {
  left: [
    { key: 'left_force_1',  name: 'Mũi chân (ADC)', color: '#f59e0b' },
    { key: 'left_force_2',  name: 'Gót chân (ADC)', color: '#ea580c' },
  ],
  right: [
    { key: 'right_force_1', name: 'Mũi chân (ADC)', color: '#f59e0b' },
    { key: 'right_force_2', name: 'Gót chân (ADC)', color: '#ea580c' },
  ],
}

const CustomTooltipAngle = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-2 shadow-lg text-xs">
      <p className="text-gray-500 mb-1">t = {(label / 1000).toFixed(2)}s</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.stroke }} className="font-medium">
          {p.name}: {Number(p.value).toFixed(1)}°
        </p>
      ))}
    </div>
  )
}

const CustomTooltipForce = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-2 shadow-lg text-xs">
      <p className="text-gray-500 mb-1">t = {(label / 1000).toFixed(2)}s</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.fill || p.stroke }} className="font-medium">
          {p.name}: {Number(p.value).toFixed(1)} N
        </p>
      ))}
    </div>
  )
}

export default function LegRealtimeChart({ readings, side }) {
  const joints = JOINT_CONFIG[side] ?? JOINT_CONFIG.left
  const forceConfs = FORCE_CONFIG[side] ?? FORCE_CONFIG.left

  const angleData = useMemo(() => {
    return readings.map((r) => {
      const point = { t: r.timestamp_ms }
      joints.forEach(({ key }) => { point[key] = r[key] ?? null })
      return point
    })
  }, [readings, joints])

  const forceData = useMemo(() => {
    return readings.map((r) => {
      const point = { t: r.timestamp_ms }
      forceConfs.forEach(({ key }) => { point[key] = r[key] ?? null })
      return point
    })
  }, [readings, forceConfs])

  if (angleData.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-52 text-gray-400 gap-2">
        <div className="w-8 h-8 border-2 border-gray-200 border-t-blue-400 rounded-full animate-spin" />
        <span className="text-sm">Chờ dữ liệu từ cảm biến...</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Góc khớp */}
      <div>
        <p className="text-xs text-gray-400 mb-1">
          Góc khớp theo thời gian ({angleData.length} điểm)
        </p>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={angleData} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={(v) => `${(v / 1000).toFixed(1)}s`}
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickLine={false}
            />
            <YAxis
              unit="°"
              domain={[-30, 80]}
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
              width={38}
            />
            <ReferenceLine y={0} stroke="#d1d5db" strokeWidth={1} strokeDasharray="4 4" />
            <Tooltip content={<CustomTooltipAngle />} />
            <Legend
              verticalAlign="top"
              align="right"
              wrapperStyle={{ fontSize: 11, paddingBottom: 4 }}
              iconType="plainline"
            />
            {joints.map(({ key, name, color, strokeWidth }) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                name={name}
                stroke={color}
                strokeWidth={strokeWidth}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Lực bàn chân FSR */}
      <div>
        <p className="text-xs text-gray-400 mb-1">FSR bàn chân (ADC)</p>
        <ResponsiveContainer width="100%" height={100}>
          <AreaChart data={forceData} margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={(v) => `${(v / 1000).toFixed(1)}s`}
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickLine={false}
            />
            <YAxis
              domain={[0, 1023]}
              tick={{ fontSize: 10, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
              width={38}
            />
            <Tooltip content={<CustomTooltipForce />} />
            <Legend
              verticalAlign="top"
              align="right"
              wrapperStyle={{ fontSize: 10, paddingBottom: 2 }}
              iconType="plainline"
            />
            {forceConfs.map(({ key, name, color }) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                name={name}
                stroke={color}
                fill={color}
                fillOpacity={0.1}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
