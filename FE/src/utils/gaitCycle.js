// Chuẩn hoá tín hiệu góc khớp theo thời gian → 1 chu kỳ dáng đi (0–100%).

export const GC_STEPS = 101
const GC_NAMES = ['Left Hip', 'Left Knee', 'Right Hip', 'Right Knee']

/** Linear interpolation of `values` at time `t`, given ascending `times`. */
export function interpAt(times, values, t) {
  const n = times.length
  if (t <= times[0]) return values[0]
  if (t >= times[n - 1]) return values[n - 1]
  let lo = 0, hi = n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= t) lo = mid; else hi = mid
  }
  const frac = (t - times[lo]) / (times[hi] - times[lo] || 1)
  return values[lo] + frac * (values[hi] - values[lo])
}

/** Detect cycle boundaries as consecutive main swing peaks of a knee-angle signal. */
export function detectCycles(times, values, minGapMs = 500) {
  const n = values.length
  if (n < 5) return []
  const vMin = Math.min(...values), vMax = Math.max(...values)
  const threshold = vMin + 0.55 * (vMax - vMin)

  const rawPeaks = []
  for (let i = 1; i < n - 1; i++) {
    if (values[i] >= values[i - 1] && values[i] >= values[i + 1] && values[i] > threshold) {
      rawPeaks.push(i)
    }
  }

  const peaks = []
  for (const idx of rawPeaks) {
    const last = peaks[peaks.length - 1]
    if (last != null && times[idx] - times[last] < minGapMs) {
      if (values[idx] > values[last]) peaks[peaks.length - 1] = idx
    } else {
      peaks.push(idx)
    }
  }

  const cycles = []
  for (let i = 0; i < peaks.length - 1; i++) {
    cycles.push([times[peaks[i]], times[peaks[i + 1]]])
  }
  return cycles
}

/** From a raw {t, 'Left Hip', 'Left Knee', 'Right Hip', 'Right Knee'} timeseries,
 *  detect cycles per leg and average hip/knee angle onto a 0–100% grid. */
export function buildAveragedCycles(timeseries) {
  if (!timeseries.length) return { data: [], leftCount: 0, rightCount: 0 }

  const times     = timeseries.map(r => r.t)
  const leftHip   = timeseries.map(r => r['Left Hip']   ?? 0)
  const leftKnee  = timeseries.map(r => r['Left Knee']  ?? 0)
  const rightHip  = timeseries.map(r => r['Right Hip']  ?? 0)
  const rightKnee = timeseries.map(r => r['Right Knee'] ?? 0)

  const leftCycles  = detectCycles(times, leftKnee)
  const rightCycles = detectCycles(times, rightKnee)

  const sums = {
    'Left Hip': new Array(GC_STEPS).fill(0), 'Left Knee': new Array(GC_STEPS).fill(0),
    'Right Hip': new Array(GC_STEPS).fill(0), 'Right Knee': new Array(GC_STEPS).fill(0),
  }

  leftCycles.forEach(([start, end]) => {
    for (let p = 0; p < GC_STEPS; p++) {
      const t = start + (p / (GC_STEPS - 1)) * (end - start)
      sums['Left Hip'][p]  += interpAt(times, leftHip, t)
      sums['Left Knee'][p] += interpAt(times, leftKnee, t)
    }
  })
  rightCycles.forEach(([start, end]) => {
    for (let p = 0; p < GC_STEPS; p++) {
      const t = start + (p / (GC_STEPS - 1)) * (end - start)
      sums['Right Hip'][p]  += interpAt(times, rightHip, t)
      sums['Right Knee'][p] += interpAt(times, rightKnee, t)
    }
  })

  const data = []
  for (let p = 0; p < GC_STEPS; p++) {
    data.push({
      pct: p,
      'Left Hip':   leftCycles.length  ? sums['Left Hip'][p]   / leftCycles.length  : null,
      'Left Knee':  leftCycles.length  ? sums['Left Knee'][p]  / leftCycles.length  : null,
      'Right Hip':  rightCycles.length ? sums['Right Hip'][p]  / rightCycles.length : null,
      'Right Knee': rightCycles.length ? sums['Right Knee'][p] / rightCycles.length : null,
    })
  }
  return { data, leftCount: leftCycles.length, rightCount: rightCycles.length }
}

/** Average several members' already-averaged single-cycle curves into one
 *  group curve — each member counts equally regardless of how many
 *  individual gait cycles they contributed. */
export function averageMemberCycles(memberResults) {
  const valid = memberResults.filter(m => m && m.data?.length)
  if (!valid.length) return { data: [], leftCount: 0, rightCount: 0 }

  const data = []
  for (let p = 0; p < GC_STEPS; p++) {
    const row = { pct: p }
    GC_NAMES.forEach((name) => {
      const vals = valid.map(m => m.data[p]?.[name]).filter(v => v != null)
      row[name] = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
    })
    data.push(row)
  }

  const leftCount  = valid.reduce((sum, m) => sum + (m.leftCount  || 0), 0)
  const rightCount = valid.reduce((sum, m) => sum + (m.rightCount || 0), 0)
  return { data, leftCount, rightCount }
}
