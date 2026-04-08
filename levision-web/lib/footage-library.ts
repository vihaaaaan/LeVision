/**
 * Viewable footage comes from the playback / processed-assets pipeline
 * (e.g. CDN, transcoded bucket, or a dedicated API) — not from the raw upload ingest path.
 */

import type { Game } from './types'

export type FootageClip = {
  id: string
  title: string
  /** ISO date string when known */
  createdAt?: string
  /**
   * Stream URL from the playback layer. Null until processing completes or when unavailable.
   */
  playbackUrl: string | null
  /**
   * Associated game data for stats display
   */
  game?: Game
}

/**
 * Load clips the user can watch. Replace with your playback API / Supabase view / edge function.
 */
export async function fetchFootageLibraryClips(): Promise<FootageClip[]> {
  // TODO: call playback library endpoint (separate from upload).
  return []
}
