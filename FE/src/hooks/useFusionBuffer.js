import { useRef, useCallback } from 'react'

// Frames from each camera are matched within this window before fusing.
// 100ms covers Brio 300 @15fps (~67ms frame interval) with margin.
const SYNC_WINDOW_MS = 100
const BUFFER_SIZE    = 5

const LATERAL_ANGLES = [
  'left_knee', 'right_knee',
  'left_hip',  'right_hip',
  'left_ankle', 'right_ankle',
  'trunk_inclination', 'knee_symmetry_index',
  'cadence', 'stride_time', 'stance_phase_pct', 'swing_phase_pct', 'step_symmetry',
]

const FRONTAL_ANGLES = [
  'left_hip_abduction', 'right_hip_abduction',
  'lateral_trunk_lean', 'left_knee_valgus', 'right_knee_valgus',
]

const POSTERIOR_ANGLES = [
  'pelvic_obliquity', 'left_hip_drop', 'right_hip_drop',
  'left_foot_progression', 'right_foot_progression',
]

// Sagittal angles frontal camera fills when lateral is absent.
const SAGITTAL_FALLBACK = ['left_knee', 'right_knee', 'left_hip', 'right_hip', 'trunk_inclination']

function round1(v) { return Math.round(v * 10) / 10 }

function fuseAngles(sources) {
  const { lateral, frontal, posterior } = sources
  const result = {}

  if (lateral) {
    for (const key of LATERAL_ANGLES) {
      if (lateral.angles[key] != null) result[key] = lateral.angles[key]
    }
  }

  if (frontal) {
    for (const key of FRONTAL_ANGLES) {
      if (frontal.angles[key] != null) result[key] = frontal.angles[key]
    }
    for (const key of SAGITTAL_FALLBACK) {
      if (result[key] == null && frontal.angles[key] != null) {
        result[key] = frontal.angles[key]
      }
    }
  }

  if (posterior) {
    for (const key of POSTERIOR_ANGLES) {
      if (posterior.angles[key] != null) result[key] = posterior.angles[key]
    }
  }

  const lk = result['left_knee'], rk = result['right_knee']
  if (lk != null && rk != null && (Math.abs(lk) + Math.abs(rk)) > 0) {
    result['knee_symmetry_index'] = round1(
      200.0 * Math.abs(lk - rk) / (Math.abs(lk) + Math.abs(rk))
    )
  }

  return result
}

export function useFusionBuffer() {
  const bufferRef = useRef({ lateral: [], frontal: [], posterior: [] })

  const pushFrame = useCallback((role, data) => {
    if (!data || data.type !== 'frame') return
    const maxKp = 17
    const frame = {
      role,
      server_ts:          data.server_ts ?? Date.now(),
      frame_id:           data.frame_id  ?? 0,
      angles:             data.angles    ?? {},
      has_3d:             data.has_3d    ?? false,
      keypoints_detected: data.keypoints_detected ?? 0,
      confidence:         Math.min((data.keypoints_detected ?? 0) / maxKp, 1.0),
    }
    const buf = bufferRef.current[role]
    if (!buf) return
    buf.push(frame)
    if (buf.length > BUFFER_SIZE) buf.shift()
  }, [])

  const getFusedFrame = useCallback(() => {
    const { lateral, frontal, posterior } = bufferRef.current

    // Prefer lateral as time reference; fall back to most recent available frame.
    const latestLateral = lateral.length ? lateral[lateral.length - 1] : null
    const latestFrontal = frontal.length ? frontal[frontal.length - 1] : null
    const latestPost    = posterior.length ? posterior[posterior.length - 1] : null

    const ref = latestLateral
      ?? [latestFrontal, latestPost].filter(Boolean).sort((a, b) => b.server_ts - a.server_ts)[0]
      ?? null

    if (!ref) return null

    const ts = ref.server_ts

    const findClosest = (buf) => {
      if (!buf.length) return null
      return buf.reduce((best, f) => {
        const d = Math.abs(f.server_ts - ts)
        return d < Math.abs((best?.server_ts ?? Infinity) - ts) ? f : best
      }, null)
    }

    const withinWindow = (f) => f && Math.abs(f.server_ts - ts) <= SYNC_WINDOW_MS

    const matchedFrontal   = findClosest(frontal)
    const matchedPosterior = findClosest(posterior)

    const sources = {
      lateral:   latestLateral,
      frontal:   withinWindow(matchedFrontal)   ? matchedFrontal   : null,
      posterior: withinWindow(matchedPosterior) ? matchedPosterior : null,
    }

    const fused = fuseAngles(sources)

    const confidence = {
      lateral:   sources.lateral   ? sources.lateral.confidence   : 0,
      frontal:   sources.frontal   ? sources.frontal.confidence   : 0,
      posterior: sources.posterior ? sources.posterior.confidence : 0,
      has_3d:    sources.lateral?.has_3d ?? false,
    }

    return {
      client_ts:      Date.now(),
      sources,
      fused,
      confidence,
      cameras_active: Object.values(sources).filter(Boolean).length,
    }
  }, [])

  return { pushFrame, getFusedFrame }
}
