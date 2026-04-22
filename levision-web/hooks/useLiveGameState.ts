'use client'

import { useEffect, useMemo, useState } from 'react'
import type { LiveGameState, LiveGameTimeline } from '@/lib/types'

type UseLiveGameStateOptions = {
  enabled?: boolean
  videoSecond?: number
}

/**
 * Loads the processed-game-state timeline once and returns the snapshot that
 * matches the current video playback second. Video second 0 maps to the first
 * snapshot (key "1"), since processed_game_state.json keys are 1-indexed.
 */
export function useLiveGameState({
  enabled = true,
  videoSecond = 0,
}: UseLiveGameStateOptions = {}) {
  const [timeline, setTimeline] = useState<LiveGameTimeline | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled || timeline || error) return
    let cancelled = false

    fetch('/api/live-game-state')
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Unable to load live state: ${response.status}`)
        }
        return (await response.json()) as LiveGameTimeline
      })
      .then((payload) => {
        if (!cancelled) setTimeline(payload)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load live state')
        }
      })

    return () => {
      cancelled = true
    }
  }, [enabled, timeline, error])

  const loading = enabled && !timeline && !error

  const liveState = useMemo<LiveGameState | null>(() => {
    if (!timeline) return null
    const { minSecond, maxSecond, snapshots } = timeline
    const requested = Math.floor(videoSecond) + 1
    const clamped = Math.min(Math.max(requested, minSecond), maxSecond)
    return snapshots[String(clamped)] ?? null
  }, [timeline, videoSecond])

  return { liveState, timeline, loading, error }
}
