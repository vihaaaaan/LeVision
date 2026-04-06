import { createClient } from '@/lib/supabase/client'

/**
 * Viewable footage comes from the playback / processed-assets pipeline
 * (e.g. CDN, transcoded bucket, or a dedicated API) — not from the raw upload ingest path.
 */

export type FootageClip = {
  id: string
  title: string
  /** ISO date string when known */
  createdAt?: string
  /**
   * Stream URL from the playback layer. Null until processing completes or when unavailable.
   */
  playbackUrl: string | null
}

export type PlayerAppearanceSegment = {
  start: number
  end: number
  timestamps: number[]
}

export type PlayerMontageSummary = {
  name: string
  firstAppearance: number
  segmentCount: number
  totalDuration: number
}

export type ClipPlayerMontage = {
  players: PlayerMontageSummary[]
  segmentsByPlayer: Record<string, PlayerAppearanceSegment[]>
  sourceRowCount: number
}

const PLAYER_TIMESTAMPS_TABLE =
  process.env.NEXT_PUBLIC_SUPABASE_PLAYER_TIMESTAMPS_TABLE ?? 'player_timestamps'

const CLIP_ID_KEYS = ['clip_id', 'game_id', 'footage_id', 'video_id', 'source_id'] as const
const TIMESTAMP_KEYS = [
  'timestamp_seconds',
  'timestamp',
  'video_second',
  'seconds',
  'time_seconds',
  'timecode',
] as const
const START_KEYS = ['start_seconds', 'start_time', 'start'] as const
const END_KEYS = ['end_seconds', 'end_time', 'end'] as const
const PLAYER_KEYS = [
  'players',
  'player_names',
  'lineup',
  'active_players',
  'on_court_players',
  'players_on_court',
] as const

const DEFAULT_SEGMENT_SPAN_SECONDS = 3
const DEFAULT_MERGE_GAP_SECONDS = 2
const PAST_GAME_ID_PREFIX = 'past-game-'

type RawTimestampRow = Record<string, unknown>

function getClipLookupIds(clipId: string): string[] {
  if (!clipId.startsWith(PAST_GAME_ID_PREFIX)) return [clipId]
  return [clipId, clipId.slice(PAST_GAME_ID_PREFIX.length)]
}

function normalizePlayerName(value: string): string {
  return value.trim().replace(/\s+/g, ' ')
}

function readField(
  row: RawTimestampRow,
  keys: readonly string[],
): unknown {
  for (const key of keys) {
    if (key in row) return row[key]
  }
  return undefined
}

function parseClockString(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null

  if (/^\d+(\.\d+)?$/.test(trimmed)) {
    return Number(trimmed)
  }

  const parts = trimmed.split(':').map((part) => Number(part))
  if (parts.some((part) => Number.isNaN(part))) return null

  let seconds = 0
  for (const part of parts) {
    seconds = seconds * 60 + part
  }

  return seconds
}

function parseSeconds(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') return parseClockString(value)
  return null
}

function parsePlayers(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .filter((item): item is string => typeof item === 'string')
      .map(normalizePlayerName)
      .filter(Boolean)
  }

  if (typeof value === 'string') {
    return value
      .split(',')
      .map(normalizePlayerName)
      .filter(Boolean)
  }

  return []
}

function filterRowsForClip(rows: RawTimestampRow[], clipId: string): RawTimestampRow[] {
  const lookupIds = new Set(getClipLookupIds(clipId))

  return rows.filter((row) => {
    const clipValue = readField(row, CLIP_ID_KEYS)
    if (clipValue == null) return true
    return lookupIds.has(String(clipValue))
  })
}

function buildPlayerSegments(rows: RawTimestampRow[]): ClipPlayerMontage {
  const rangesByPlayer = new Map<string, Array<{ start: number; end: number; timestamp: number }>>()

  const sortedRows = [...rows].sort((a, b) => {
    const aStart = parseSeconds(readField(a, START_KEYS)) ?? parseSeconds(readField(a, TIMESTAMP_KEYS)) ?? 0
    const bStart = parseSeconds(readField(b, START_KEYS)) ?? parseSeconds(readField(b, TIMESTAMP_KEYS)) ?? 0
    return aStart - bStart
  })

  for (const row of sortedRows) {
    const players = parsePlayers(readField(row, PLAYER_KEYS))
    const start =
      parseSeconds(readField(row, START_KEYS)) ??
      parseSeconds(readField(row, TIMESTAMP_KEYS))
    const end =
      parseSeconds(readField(row, END_KEYS)) ??
      (start != null ? start + DEFAULT_SEGMENT_SPAN_SECONDS : null)

    if (players.length === 0 || start == null || end == null) continue

    for (const player of players) {
      const next = rangesByPlayer.get(player) ?? []
      next.push({ start, end: Math.max(start, end), timestamp: start })
      rangesByPlayer.set(player, next)
    }
  }

  const segmentsByPlayer: Record<string, PlayerAppearanceSegment[]> = {}

  for (const [player, ranges] of rangesByPlayer.entries()) {
    const uniqueSorted = [...ranges].sort((a, b) => a.start - b.start)
    const segments: PlayerAppearanceSegment[] = []

    for (const range of uniqueSorted) {
      const lastSegment = segments.at(-1)
      if (!lastSegment) {
        segments.push({
          start: Math.max(0, range.start),
          end: Math.max(range.end, range.start),
          timestamps: [range.timestamp],
        })
        continue
      }

      if (range.start - lastSegment.end <= DEFAULT_MERGE_GAP_SECONDS) {
        lastSegment.end = Math.max(lastSegment.end, range.end)
        lastSegment.timestamps.push(range.timestamp)
        continue
      }

      segments.push({
        start: Math.max(0, range.start),
        end: Math.max(range.end, range.start),
        timestamps: [range.timestamp],
      })
    }

    segmentsByPlayer[player] = segments
  }

  const players = Object.entries(segmentsByPlayer)
    .map(([name, segments]) => ({
      name,
      firstAppearance: segments[0]?.start ?? 0,
      segmentCount: segments.length,
      totalDuration: segments.reduce((total, segment) => total + (segment.end - segment.start), 0),
    }))
    .sort((a, b) => a.firstAppearance - b.firstAppearance || a.name.localeCompare(b.name))

  return {
    players,
    segmentsByPlayer,
    sourceRowCount: sortedRows.length,
  }
}

/**
 * Load clips the user can watch. Replace with your playback API / Supabase view / edge function.
 */
export async function fetchFootageLibraryClips(): Promise<FootageClip[]> {
  // TODO: call playback library endpoint (separate from upload).
  return []
}

export async function fetchClipPlayerMontage(clipId: string): Promise<ClipPlayerMontage> {
  const supabase = createClient()
  const { data, error } = await supabase.from(PLAYER_TIMESTAMPS_TABLE).select('*')

  if (error) throw error

  const rows = filterRowsForClip((data ?? []) as RawTimestampRow[], clipId)
  return buildPlayerSegments(rows)
}
