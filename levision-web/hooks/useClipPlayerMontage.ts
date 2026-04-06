'use client'

import { useEffect, useState } from 'react'
import {
  fetchClipPlayerMontage,
  type ClipPlayerMontage,
} from '@/lib/footage-library'

export function useClipPlayerMontage(clipId: string | null) {
  const [state, setState] = useState<{
    clipId: string | null
    montage: ClipPlayerMontage | null
    error: string | null
    loading: boolean
  }>({
    clipId: null,
    montage: null,
    error: null,
    loading: false,
  })

  useEffect(() => {
    if (!clipId) return

    let cancelled = false

    fetchClipPlayerMontage(clipId)
      .then((nextMontage) => {
        if (!cancelled) {
          setState({
            clipId,
            montage: nextMontage,
            error: null,
            loading: false,
          })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({
            clipId,
            montage: null,
            error: 'Could not load player timestamps.',
            loading: false,
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [clipId])

  return {
    montage: state.clipId === clipId ? state.montage : null,
    loading: clipId != null && state.clipId !== clipId ? true : state.loading,
    error: state.clipId === clipId ? state.error : null,
  }
}
