import { GetObjectCommand, NoSuchKey, S3Client } from '@aws-sdk/client-s3'
import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import type {
  LiveGameState,
  LivePlay,
  LiveGameTimeline,
  LivePlayerState,
  LiveTeamState,
} from '@/lib/types'

export const runtime = 'nodejs'

function createR2Client() {
  return new S3Client({
    region: 'auto',
    endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: process.env.R2_ACCESS_KEY_ID as string,
      secretAccessKey: process.env.R2_SECRET_ACCESS_KEY as string,
    },
  })
}

async function fetchR2Json(r2: S3Client, key: string): Promise<unknown> {
  const res = await r2.send(new GetObjectCommand({ Bucket: process.env.R2_BUCKET, Key: key }))
  const body = await res.Body?.transformToString('utf8')
  if (!body) throw new Error(`Empty response for R2 key: ${key}`)
  return JSON.parse(body)
}

async function fetchOptionalR2Json<T>(r2: S3Client, key: string): Promise<T | null> {
  try {
    return (await fetchR2Json(r2, key)) as T
  } catch (error) {
    if (error instanceof NoSuchKey) return null
    if (error instanceof Error && /NoSuchKey|The specified key does not exist/i.test(error.message)) {
      return null
    }
    throw error
  }
}

type PlayerLookupEntry = { name: string; teamName: string }
type PlayerLookup = Map<number, PlayerLookupEntry>

type RawPlayerStats = {
  pts?: number
  reb?: number
  ast?: number
  stl?: number
  blk?: number
}

type RawTeamState = {
  on_court?: Array<number | string>
  player_stats?: Record<string, RawPlayerStats>
}

type RawSnapshot = {
  game_clock?: string
  period?: number
  home_team?: RawTeamState
  visitor_team?: RawTeamState
  recent_events?: string[]
}

type RawPlay = {
  actionNumber?: number
  description?: string
  period?: number
  clock?: string
  scoreHome?: string
  scoreAway?: string
  teamTricode?: string
  videoAvailable?: number
  actionId?: number
}

function buildPlayerLookup(entries: Array<Record<string, unknown>>): PlayerLookup {
  const map: PlayerLookup = new Map()
  for (const entry of entries) {
    const personId = Number(entry.personId)
    if (!personId) continue
    const firstName = typeof entry.firstName === 'string' ? entry.firstName : ''
    const familyName = typeof entry.familyName === 'string' ? entry.familyName : ''
    const nameI = typeof entry.nameI === 'string' ? entry.nameI : ''
    const name = `${firstName} ${familyName}`.trim() || nameI || `Player ${personId}`
    const teamName =
      (typeof entry.teamName === 'string' && entry.teamName) ||
      (typeof entry.teamCity === 'string' && entry.teamCity) ||
      'Unknown'
    map.set(personId, { name, teamName })
  }
  return map
}

function normalizePlayer(
  playerId: string,
  stats: RawPlayerStats,
  onCourt: Set<string>,
  lookup: PlayerLookup,
): LivePlayerState {
  const entry = lookup.get(Number(playerId))
  return {
    id: playerId,
    name: entry?.name ?? `Player ${playerId}`,
    onCourt: onCourt.has(playerId),
    points: stats.pts ?? 0,
    rebounds: stats.reb ?? 0,
    assists: stats.ast ?? 0,
    steals: stats.stl ?? 0,
    blocks: stats.blk ?? 0,
  }
}

function normalizeTeam(
  side: 'home' | 'away',
  team: RawTeamState | undefined,
  lookup: PlayerLookup,
): LiveTeamState {
  const onCourt = (team?.on_court ?? []).map(String)
  const onCourtSet = new Set(onCourt)
  const rawStats = team?.player_stats ?? {}

  const playerStats = Object.keys(rawStats)
    .map((pid) => normalizePlayer(pid, rawStats[pid], onCourtSet, lookup))
    .sort((a, b) => {
      if (a.onCourt !== b.onCourt) return a.onCourt ? -1 : 1
      return a.name.localeCompare(b.name)
    })

  const teamFromOnCourt = onCourt[0] ? lookup.get(Number(onCourt[0]))?.teamName : undefined
  const teamFromRoster = Object.keys(rawStats)
    .map((pid) => lookup.get(Number(pid))?.teamName)
    .find((value): value is string => Boolean(value))

  return {
    teamName: teamFromOnCourt ?? teamFromRoster ?? (side === 'home' ? 'Home Team' : 'Away Team'),
    onCourt,
    playerStats,
  }
}

function buildSnapshots(
  state: Record<string, RawSnapshot>,
  lookup: PlayerLookup,
): Record<string, LiveGameState> {
  const snapshots: Record<string, LiveGameState> = {}
  for (const key of Object.keys(state)) {
    const entry = state[key]
    snapshots[key] = {
      videoSecond: Number(key),
      clock: entry.game_clock ?? '00:00',
      period: Number(entry.period ?? 0),
      homeTeam: normalizeTeam('home', entry.home_team, lookup),
      awayTeam: normalizeTeam('away', entry.visitor_team, lookup),
      recentEvents: entry.recent_events ?? [],
    }
  }
  return snapshots
}

function formatPlayClock(clock: string | undefined): string {
  if (!clock) return '--:--'
  const match = clock.match(/PT(?:(\d+)M)?([\d.]+)S/i)
  if (!match) return clock
  const minutes = Number(match[1] ?? 0)
  const seconds = Math.floor(Number(match[2] ?? 0))
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function buildPlays(rawPlays: RawPlay[]): LivePlay[] {
  return rawPlays
    .filter((play) => typeof play.description === 'string' && typeof play.period === 'number')
    .map((play, index) => ({
      id: String(play.actionId ?? play.actionNumber ?? index),
      actionNumber: Number(play.actionNumber ?? index),
      description: play.description ?? '',
      period: Number(play.period ?? 0),
      clock: formatPlayClock(play.clock),
      scoreHome: play.scoreHome || null,
      scoreAway: play.scoreAway || null,
      teamAbbrev: play.teamTricode || null,
      videoAvailable: Boolean(play.videoAvailable),
    }))
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const clipId = searchParams.get('clipId')

  if (!clipId) {
    return NextResponse.json({ error: 'Missing clipId' }, { status: 400 })
  }

  try {
    const supabase = await createClient()
    const {
      data: { user },
    } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const { data: clip, error: dbError } = await supabase
      .from('footage')
      .select('vision_results_key, vision_status')
      .eq('id', clipId)
      .single()

    if (dbError || !clip) {
      return NextResponse.json({ error: 'Clip not found' }, { status: 404 })
    }
    if (clip.vision_status !== 'completed' || !clip.vision_results_key) {
      return NextResponse.json({ error: 'Results not ready' }, { status: 404 })
    }

    const r2 = createR2Client()
    const clipDir = clip.vision_results_key.replace('/game_state.json', '')

    const [state, playerBox, rawPlays] = await Promise.all([
      fetchR2Json(r2, clip.vision_results_key) as Promise<Record<string, RawSnapshot>>,
      fetchR2Json(r2, `${clipDir}/player_boxscore.json`) as Promise<Array<Record<string, unknown>>>,
      fetchOptionalR2Json<RawPlay[]>(r2, `${clipDir}/pbp_raw.json`),
    ])

    const lookup = buildPlayerLookup(playerBox)
    const snapshots = buildSnapshots(state, lookup)
    const plays = buildPlays(rawPlays ?? [])
    const secondKeys = Object.keys(snapshots)
      .map(Number)
      .filter(Number.isFinite)
      .sort((a, b) => a - b)

    if (secondKeys.length === 0) {
      return NextResponse.json({ error: 'No game state data' }, { status: 404 })
    }

    const timeline: LiveGameTimeline = {
      minSecond: secondKeys[0],
      maxSecond: secondKeys[secondKeys.length - 1],
      snapshots,
      plays,
    }

    return NextResponse.json(timeline)
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Failed to load game state' },
      { status: 500 },
    )
  }
}
