import { useEffect, useRef, useState } from 'react'
import useAuthStore from '../store/authStore'

export function useWebSocket(sessionId) {
  const { token } = useAuthStore()
  const ws = useRef(null)
  const [readings, setReadings] = useState([])
  const [status, setStatus] = useState('disconnected')
  const MAX_POINTS = 300

  useEffect(() => {
    if (!sessionId || !token) return
    let mounted = true
    setStatus('connecting')

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/realtime/${sessionId}?token=${token}`
    ws.current = new WebSocket(url)

    ws.current.onopen = () => {
      if (mounted) setStatus('connected')
    }

    ws.current.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'reading' && mounted) {
          setReadings((prev) => {
            const next = [...prev, msg.data]
            return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next
          })
        }
      } catch {
        // Malformed JSON from server — skip frame
      }
    }

    ws.current.onclose = () => { if (mounted) setStatus('disconnected') }
    ws.current.onerror = () => { if (mounted) setStatus('error') }

    const ping = setInterval(() => {
      if (ws.current?.readyState === WebSocket.OPEN) {
        ws.current.send('ping')
      }
    }, 25000)

    return () => {
      mounted = false
      clearInterval(ping)
      ws.current?.close()
    }
  }, [sessionId, token])

  const clear = () => setReadings([])

  return { readings, status, clear }
}
