'use client'

import { useEffect, useState } from 'react'
import {
  fetchFootageLibraryClips,
  type FootageClip,
} from '@/lib/footage-library'

export function useFootageLibrary() {
  const [clips, setClips] = useState<FootageClip[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchFootageLibraryClips()
      .then((items) => {
        if (!cancelled) setClips(items)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load your library.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { clips, loading, error }
}

export type { FootageClip }
