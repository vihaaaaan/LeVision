import { NextResponse } from 'next/server'

export const runtime = 'nodejs'

const ESPN_BASE    = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
const ESPN_HEADERS = { 'User-Agent': 'LeVision/1.0' }

// ── Types ─────────────────────────────────────────────────────────────────────

type ESPNCompetitor = {
  homeAway: 'home' | 'away'
  team: { id?: string; displayName?: string; abbreviation?: string }
  score?: string | number | { displayValue?: string }
}

type ESPNEvent = {
  id: string
  date: string
  competitions?: Array<{
    competitors?: ESPNCompetitor[]
    status?: { type?: { completed?: boolean; description?: string } }
  }>
}

export type ParsedGame = {
  espn_game_id: string
  date: string
  home_team_id: string
  home_team: string
  home_abbrev: string
  away_team_id: string
  away_team: string
  away_abbrev: string
  home_score: string | null
  away_score: string | null
  completed: boolean
  status_label: string
  label: string
}

// ── ESPN wrapper ──────────────────────────────────────────────────────────────

async function fetchTeamScheduleByType(teamId: string, season: string, seasontype: 2 | 3) {
  const res = await fetch(
    `${ESPN_BASE}/teams/${teamId}/schedule?season=${season}&seasontype=${seasontype}`,
    { headers: ESPN_HEADERS, next: { revalidate: 3600 } },
  )
  if (!res.ok) throw new Error(`ESPN team schedule failed for ${teamId} (seasontype=${seasontype}): ${res.status}`)
  return res.json() as Promise<{ events?: ESPNEvent[] }>
}

// Fetches regular season + playoffs in parallel and merges
async function fetchTeamSchedule(teamId: string, season: string): Promise<ESPNEvent[]> {
  const [regular, playoffs] = await Promise.all([
    fetchTeamScheduleByType(teamId, season, 2),
    fetchTeamScheduleByType(teamId, season, 3),
  ])
  return [...(regular.events ?? []), ...(playoffs.events ?? [])]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseScore(score: ESPNCompetitor['score']): string | null {
  if (score === undefined || score === null) return null
  if (typeof score === 'string') return score
  if (typeof score === 'number') return String(score)
  return score.displayValue ?? null
}

function parseEvent(event: ESPNEvent): ParsedGame {
  const comp = event.competitions?.[0]
  const home = comp?.competitors?.find((c) => c.homeAway === 'home')
  const away = comp?.competitors?.find((c) => c.homeAway === 'away')
  const status = comp?.status?.type
  return {
    espn_game_id:  event.id,
    date:          event.date,
    home_team_id:  home?.team.id          ?? '',
    home_team:     home?.team.displayName  ?? 'Home',
    home_abbrev:   home?.team.abbreviation ?? '',
    away_team_id:  away?.team.id          ?? '',
    away_team:     away?.team.displayName  ?? 'Away',
    away_abbrev:   away?.team.abbreviation ?? '',
    home_score:   parseScore(home?.score),
    away_score:   parseScore(away?.score),
    completed:    status?.completed ?? false,
    status_label: status?.description ?? '',
    label:        `${away?.team.abbreviation ?? 'Away'} @ ${home?.team.abbreviation ?? 'Home'}`,
  }
}

// ── Route ─────────────────────────────────────────────────────────────────────
// Expects resolved ESPN team IDs from /api/teams/search — not team name strings.
// Required: season (end-year e.g. "2025"), team_one_id (ESPN numeric team ID)
// Optional: team_two_id — narrows results to head-to-head matchups only

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const season      = searchParams.get('season')      // e.g. "2025"
  const team_one_id = searchParams.get('team_one_id') // ESPN team ID, e.g. "13"
  const team_two_id = searchParams.get('team_two_id') // optional

  if (!season || !team_one_id) {
    return NextResponse.json({ error: 'season and team_one_id are required' }, { status: 400 })
  }

  try {
    let games: ParsedGame[]

    if (team_two_id) {
      const [sched1, sched2] = await Promise.all([
        fetchTeamSchedule(team_one_id, season),
        fetchTeamSchedule(team_two_id, season),
      ])
      const parsed1 = sched1.map(parseEvent).filter((g) => g.completed)
      const parsed2 = sched2.map(parseEvent).filter((g) => g.completed)
      const ids2 = new Set(parsed2.map((g) => g.espn_game_id))
      games = parsed1.filter((g) => ids2.has(g.espn_game_id))
    } else {
      const events = await fetchTeamSchedule(team_one_id, season)
      games = events.map(parseEvent).filter((g) => g.completed)
    }

    games = games
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
      .slice(0, 20)

    return NextResponse.json({ games })
  } catch (err) {
    console.error('games/search failed', err)
    return NextResponse.json({ error: 'Failed to fetch games' }, { status: 500 })
  }
}
