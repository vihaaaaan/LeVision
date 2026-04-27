import { readFile } from 'fs/promises'
import path from 'path'
import { NextResponse } from 'next/server'
import type {
  LiveGameState,
  LivePlay,
  LiveGameTimeline,
  LivePlayerState,
  LiveTeamState,
} from '@/lib/types'

const ROOT_DIR = process.cwd()
const STATE_PATH = path.resolve(ROOT_DIR, '../vision/processed_game_state.json')
const PLAYER_BOX_PATH = path.resolve(ROOT_DIR, '../vision/data/nba/player_boxscore.json')
const PBP_PATH = path.resolve(ROOT_DIR, '../vision/data/nba/pbp_raw.json')

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
    const nameI = typeof entry.nameI === 'string' ? entry.nameI : ''
    const firstName = typeof entry.firstName === 'string' ? entry.firstName : ''
    const familyName = typeof entry.familyName === 'string' ? entry.familyName : ''
    const fullName = `${firstName} ${familyName}`.trim()
    // Prefer full name so the Supabase `players.full_name` headshot lookup matches.
    const name = fullName || nameI || `Player ${personId}`
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
      if (b.points !== a.points) return b.points - a.points
      return a.name.localeCompare(b.name)
    })

  const teamFromOnCourt = onCourt[0]
    ? lookup.get(Number(onCourt[0]))?.teamName
    : undefined
  const teamFromRoster = Object.keys(rawStats)
    .map((pid) => lookup.get(Number(pid))?.teamName)
    .find((value): value is string => Boolean(value))

  return {
    teamName:
      teamFromOnCourt ?? teamFromRoster ?? (side === 'home' ? 'Home Team' : 'Away Team'),
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
    const snapshot: LiveGameState = {
      videoSecond: Number(key),
      clock: entry.game_clock ?? '00:00',
      period: Number(entry.period ?? 0),
      homeTeam: normalizeTeam('home', entry.home_team, lookup),
      awayTeam: normalizeTeam('away', entry.visitor_team, lookup),
    }
    snapshots[key] = snapshot
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

export async function GET() {
  try {
    const [stateRaw, playerBoxRaw, pbpRaw] = await Promise.all([
      readFile(STATE_PATH, 'utf8'),
      readFile(PLAYER_BOX_PATH, 'utf8'),
      readFile(PBP_PATH, 'utf8'),
    ])

    const state = JSON.parse(stateRaw) as Record<string, RawSnapshot>
    const playerBox = JSON.parse(playerBoxRaw) as Array<Record<string, unknown>>
    const rawPlays = JSON.parse(pbpRaw) as RawPlay[]
    const lookup = buildPlayerLookup(playerBox)

    const snapshots = buildSnapshots(state, lookup)
    const plays = buildPlays(rawPlays)
    const secondKeys = Object.keys(snapshots)
      .map((k) => Number(k))
      .filter((n) => Number.isFinite(n))
      .sort((a, b) => a - b)

    if (secondKeys.length === 0) {
      return NextResponse.json({ error: 'No live game state available' }, { status: 404 })
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
      { error: error instanceof Error ? error.message : 'Unable to read live game state' },
      { status: 500 },
    )
  }
}
