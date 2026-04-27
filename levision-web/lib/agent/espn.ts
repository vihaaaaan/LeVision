const SCOREBOARD_URL =
  'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
const SUMMARY_URL =
  'https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary'
const TEAM_SCHEDULE_URL =
  'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams'

export type GameResult = {
  eventId: string
  date: string
  status: string
  homeTeam: string
  homeTeamAbbr: string
  awayTeam: string
  awayTeamAbbr: string
  homeScore: number | null
  awayScore: number | null
}

export type PlayerBoxscore = {
  id: string
  name: string
  teamAbbr: string
  starter: boolean
  didNotPlay: boolean
  minutes: string
  points: number | null
  rebounds: number | null
  assists: number | null
  steals: number | null
  blocks: number | null
  turnovers: number | null
  fgMade: number | null
  fgAttempted: number | null
  threeMade: number | null
  threeAttempted: number | null
  ftMade: number | null
  ftAttempted: number | null
  plusMinus: number | null
}

export type TeamBoxscore = {
  id: string
  name: string
  abbreviation: string
  score: number | null
  fieldGoalPct: string | null
  threePointPct: string | null
  freeThrowPct: string | null
  rebounds: number | null
  assists: number | null
  turnovers: number | null
  fastBreakPoints: number | null
  pointsInPaint: number | null
  largestLead: number | null
}

export type Play = {
  period: number
  clock: string
  text: string
  scoreHome: number | null
  scoreAway: number | null
}

export type MomentumRun = {
  team: 'home' | 'away'
  teamName: string
  points: number
  opponentPoints: number
  period: number
  startClock: string
  endClock: string
  startScore: string
  endScore: string
}

export type ParsedGameSummary = {
  eventId: string
  date: string
  status: string
  venue: string | null
  homeTeam: TeamBoxscore
  awayTeam: TeamBoxscore
  players: PlayerBoxscore[]
}

function toDateParam(date: string): string {
  return date.replace(/-/g, '')
}

function safeInt(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? Math.round(n) : null
}

function parseMinutes(value: unknown): string {
  const text = String(value ?? '').trim()
  if (!text || text === '-' || text === '--') return '0:00'
  return text
}

function parseMadeAttempted(value: unknown): [number | null, number | null] {
  if (!value) return [null, null]
  const text = String(value).trim()
  if (text.includes('-')) {
    const [l, r] = text.split('-')
    return [safeInt(l), safeInt(r)]
  }
  return [safeInt(text), null]
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeKey(k: string): string {
  return k.toLowerCase().replace(/[^a-z0-9]/g, '')
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildStatMap(stats: unknown[], keys: string[]): Record<string, unknown> {
  const map: Record<string, unknown> = {}
  stats.forEach((v, i) => {
    const key = keys[i] ? normalizeKey(keys[i]) : `stat_${i}`
    map[key] = v
  })
  return map
}

function firstOf(map: Record<string, unknown>, candidates: string[]): unknown {
  for (const c of candidates) {
    const v = map[normalizeKey(c)]
    if (v !== undefined && v !== null) return v
  }
  return null
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function espnFetch(url: string): Promise<any> {
  const res = await fetch(url, { cache: 'no-store' })
  if (!res.ok) throw new Error(`ESPN fetch failed: ${res.status} ${url}`)
  return res.json()
}

export async function fetchScoreboard(date: string) {
  return espnFetch(`${SCOREBOARD_URL}?dates=${toDateParam(date)}`)
}

export async function fetchGameSummary(eventId: string) {
  return espnFetch(
    `${SUMMARY_URL}?region=us&lang=en&contentorigin=espn&event=${eventId}`
  )
}

// Season year = year the season ends (e.g. 2025 for 2024-25 season)
function seasonFromDate(date: string): number {
  const d = new Date(date)
  // NBA season ends in June; if month >= 10 (Oct) we're in the next calendar year's season
  return d.getMonth() >= 9 ? d.getFullYear() + 1 : d.getFullYear()
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function findGameByTeamAndDate(espnTeamId: string, date: string): Promise<GameResult | null> {
  const season = seasonFromDate(date)
  const targetDate = date.slice(0, 10)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const data: any = await espnFetch(
    `${TEAM_SCHEDULE_URL}/${espnTeamId}/schedule?season=${season}`
  )
  const events: any[] = data?.events ?? []
  for (const event of events) {
    const comp = event?.competitions?.[0]
    if (!comp) continue
    const eventDate = String(comp.date ?? event.date ?? '').slice(0, 10)
    if (eventDate !== targetDate) continue

    const competitors: any[] = comp.competitors ?? []
    const home = competitors.find((c: any) => c.homeAway === 'home')
    const away = competitors.find((c: any) => c.homeAway === 'away')

    return {
      eventId: String(event.id ?? ''),
      date: eventDate,
      status: String(comp?.status?.type?.name ?? 'unknown'),
      homeTeam: String(home?.team?.displayName ?? ''),
      homeTeamAbbr: String(home?.team?.abbreviation ?? ''),
      awayTeam: String(away?.team?.displayName ?? ''),
      awayTeamAbbr: String(away?.team?.abbreviation ?? ''),
      homeScore: safeInt(home?.score),
      awayScore: safeInt(away?.score),
    }
  }
  return null
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function findTeamGamesOnScoreboard(scoreboard: any, teamAbbr: string): GameResult[] {
  const abbr = teamAbbr.toUpperCase()
  const results: GameResult[] = []

  for (const event of scoreboard?.events ?? []) {
    const comp = event?.competitions?.[0]
    if (!comp) continue

    const competitors: any[] = comp.competitors ?? []
    const found = competitors.some(
      (c: any) => String(c?.team?.abbreviation ?? '').toUpperCase() === abbr
    )
    if (!found) continue

    const home = competitors.find((c: any) => c.homeAway === 'home')
    const away = competitors.find((c: any) => c.homeAway === 'away')

    results.push({
      eventId: String(event.id ?? ''),
      date: String(comp.date ?? event.date ?? '').slice(0, 10),
      status: String(comp?.status?.type?.name ?? 'unknown'),
      homeTeam: String(home?.team?.displayName ?? home?.team?.name ?? ''),
      homeTeamAbbr: String(home?.team?.abbreviation ?? ''),
      awayTeam: String(away?.team?.displayName ?? away?.team?.name ?? ''),
      awayTeamAbbr: String(away?.team?.abbreviation ?? ''),
      homeScore: safeInt(home?.score),
      awayScore: safeInt(away?.score),
    })
  }

  return results
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function parseGameSummary(summary: any, eventId: string): ParsedGameSummary {
  const header = summary?.header ?? {}
  const comp = header?.competitions?.[0] ?? summary?.competitions?.[0] ?? {}
  const competitors: any[] = comp?.competitors ?? []

  const home = competitors.find((c: any) => c.homeAway === 'home') ?? competitors[0]
  const away = competitors.find((c: any) => c.homeAway === 'away') ?? competitors[1]

  function teamBoxscore(competitor: any, boxscoreTeam: any): TeamBoxscore {
    const statList: any[] = boxscoreTeam?.statistics ?? []
    const statMap: Record<string, unknown> = {}
    for (const s of statList) {
      const aliases = [s.name, s.abbreviation, s.displayName, s.shortDisplayName, s.label]
      const value = s.displayValue ?? s.value
      for (const alias of aliases) {
        if (alias) statMap[normalizeKey(String(alias))] = value
      }
    }

    return {
      id: String(competitor?.team?.id ?? boxscoreTeam?.team?.id ?? ''),
      name: String(
        competitor?.team?.displayName ??
        competitor?.team?.name ??
        boxscoreTeam?.team?.displayName ??
        ''
      ),
      abbreviation: String(
        competitor?.team?.abbreviation ?? boxscoreTeam?.team?.abbreviation ?? ''
      ),
      score: safeInt(competitor?.score),
      fieldGoalPct: String(firstOf(statMap, ['fieldGoalPercentage', 'fieldGoalPct', 'fgPct']) ?? ''),
      threePointPct: String(firstOf(statMap, ['threePointFieldGoalPercentage', 'threePointPct', '3ptPct']) ?? ''),
      freeThrowPct: String(firstOf(statMap, ['freeThrowPercentage', 'freeThrowPct', 'ftPct']) ?? ''),
      rebounds: safeInt(firstOf(statMap, ['totalRebounds', 'rebounds', 'reb'])),
      assists: safeInt(firstOf(statMap, ['assists', 'ast'])),
      turnovers: safeInt(firstOf(statMap, ['turnovers', 'to', 'tov'])),
      fastBreakPoints: safeInt(firstOf(statMap, ['fastBreakPoints', 'fastBreak'])),
      pointsInPaint: safeInt(firstOf(statMap, ['pointsInPaint', 'paintPoints'])),
      largestLead: safeInt(firstOf(statMap, ['largestLead'])),
    }
  }

  const boxscoreTeams: any[] = summary?.boxscore?.teams ?? []
  const homeBoxTeam = boxscoreTeams.find(
    (t: any) => String(t?.team?.id ?? '') === String(home?.team?.id ?? '')
  ) ?? boxscoreTeams[0]
  const awayBoxTeam = boxscoreTeams.find(
    (t: any) => String(t?.team?.id ?? '') === String(away?.team?.id ?? '')
  ) ?? boxscoreTeams[1]

  const players = parsePlayers(summary, eventId)

  const venue =
    comp?.venue?.fullName ??
    summary?.gameInfo?.venue?.fullName ??
    null

  return {
    eventId,
    date: String(comp?.date ?? '').slice(0, 10),
    status: String(comp?.status?.type?.name ?? 'unknown'),
    venue: venue ? String(venue) : null,
    homeTeam: teamBoxscore(home, homeBoxTeam ?? {}),
    awayTeam: teamBoxscore(away, awayBoxTeam ?? {}),
    players,
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parsePlayers(summary: any, gameId: string): PlayerBoxscore[] {
  const results: PlayerBoxscore[] = []
  const seen = new Set<string>()

  function ingestBlock(block: any, teamAbbr: string) {
    const rawKeys: string[] = block?.keys ?? block?.labels ?? []
    const athletes: any[] = block?.athletes ?? []
    for (const entry of athletes) {
      const athlete = entry?.athlete ?? {}
      const id = String(athlete?.id ?? entry?.id ?? '')
      if (!id || seen.has(id)) continue
      seen.add(id)

      const name =
        athlete?.fullName ?? athlete?.displayName ?? athlete?.shortName ?? `Player-${id}`

      const rawStats = entry?.stats ?? entry?.statistics ?? []
      const statMap =
        rawKeys.length === rawStats.length
          ? buildStatMap(rawStats, rawKeys)
          : buildStatMap(rawStats, rawKeys)

      const allMap = { ...statMap }

      const didNotPlay =
        entry?.didNotPlay === true ||
        String(parseMinutes(firstOf(allMap, ['minutes', 'min']))).trim() === '0:00' ||
        String(parseMinutes(firstOf(allMap, ['minutes', 'min']))).trim() === ''

      const [fgMade, fgAttempted] = parseMadeAttempted(
        firstOf(allMap, ['fieldGoalsMadeFieldGoalsAttempted', 'fieldGoals', 'fg'])
      )
      const [threeMade, threeAttempted] = parseMadeAttempted(
        firstOf(allMap, [
          'threePointFieldGoalsMadeThreePointFieldGoalsAttempted',
          'threePointFieldGoals',
          '3pt',
        ])
      )
      const [ftMade, ftAttempted] = parseMadeAttempted(
        firstOf(allMap, ['freeThrowsMadeFreeThrowsAttempted', 'freeThrows', 'ft'])
      )

      results.push({
        id,
        name: String(name),
        teamAbbr,
        starter: entry?.starter === true,
        didNotPlay,
        minutes: parseMinutes(firstOf(allMap, ['minutes', 'min'])),
        points: safeInt(firstOf(allMap, ['points', 'pts'])),
        rebounds: safeInt(firstOf(allMap, ['rebounds', 'reb', 'totalRebounds'])),
        assists: safeInt(firstOf(allMap, ['assists', 'ast'])),
        steals: safeInt(firstOf(allMap, ['steals', 'stl'])),
        blocks: safeInt(firstOf(allMap, ['blocks', 'blk'])),
        turnovers: safeInt(firstOf(allMap, ['turnovers', 'to', 'tov'])),
        fgMade,
        fgAttempted,
        threeMade,
        threeAttempted,
        ftMade,
        ftAttempted,
        plusMinus: safeInt(
          firstOf(allMap, ['plusMinus', 'plusminus', '+/-'])
        ),
      })
    }
  }

  // boxscore.players format
  const playerBlocks: any[] = summary?.boxscore?.players ?? []
  for (const teamBlock of playerBlocks) {
    const abbr = String(teamBlock?.team?.abbreviation ?? '')
    for (const group of teamBlock?.statistics ?? []) {
      ingestBlock(group, abbr)
    }
  }

  // boxscore.teams[].athletes format
  const boxTeams: any[] = summary?.boxscore?.teams ?? []
  for (const teamBlock of boxTeams) {
    const abbr = String(teamBlock?.team?.abbreviation ?? '')
    for (const group of teamBlock?.athletes ?? []) {
      ingestBlock(group, abbr)
    }
  }

  return results
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function parsePlayByPlay(summary: any, limit = 75): Play[] {
  const plays: any[] = summary?.plays ?? []
  return plays.slice(0, limit).map((p: any) => ({
    period: safeInt(p?.period?.number ?? p?.period) ?? 0,
    clock: String(p?.clock?.displayValue ?? p?.clock ?? ''),
    text: String(p?.text ?? p?.shortText ?? ''),
    scoreHome: safeInt(p?.homeScore ?? p?.homeTeamScore),
    scoreAway: safeInt(p?.awayScore ?? p?.awayTeamScore),
  }))
}

export function computeMomentumRuns(
  plays: Play[],
  homeTeamName: string,
  awayTeamName: string,
  minRun = 7
): MomentumRun[] {
  const runs: MomentumRun[] = []

  // Only consider plays that have score data and where score changes
  const scored = plays.filter(
    (p) => p.scoreHome !== null && p.scoreAway !== null
  )
  if (scored.length < 2) return runs

  let runTeam: 'home' | 'away' | null = null
  let runStart = scored[0]
  let runHomeStart = scored[0].scoreHome!
  let runAwayStart = scored[0].scoreAway!
  let lastHome = scored[0].scoreHome!
  let lastAway = scored[0].scoreAway!

  const flush = (endPlay: Play) => {
    if (!runTeam) return
    const homeScored = endPlay.scoreHome! - runHomeStart
    const awayScored = endPlay.scoreAway! - runAwayStart
    const runPts = runTeam === 'home' ? homeScored : awayScored
    const oppPts = runTeam === 'home' ? awayScored : homeScored
    if (runPts >= minRun) {
      runs.push({
        team: runTeam,
        teamName: runTeam === 'home' ? homeTeamName : awayTeamName,
        points: runPts,
        opponentPoints: oppPts,
        period: runStart.period,
        startClock: runStart.clock,
        endClock: endPlay.clock,
        startScore: `${awayTeamName} ${runAwayStart} - ${homeTeamName} ${runHomeStart}`,
        endScore: `${awayTeamName} ${endPlay.scoreAway} - ${homeTeamName} ${endPlay.scoreHome}`,
      })
    }
  }

  for (const play of scored.slice(1)) {
    const homeDelta = play.scoreHome! - lastHome
    const awayDelta = play.scoreAway! - lastAway

    if (homeDelta > 0 && awayDelta === 0) {
      if (runTeam !== 'home') {
        flush(play)
        runTeam = 'home'
        runStart = play
        runHomeStart = lastHome
        runAwayStart = lastAway
      }
    } else if (awayDelta > 0 && homeDelta === 0) {
      if (runTeam !== 'away') {
        flush(play)
        runTeam = 'away'
        runStart = play
        runHomeStart = lastHome
        runAwayStart = lastAway
      }
    } else if (homeDelta > 0 && awayDelta > 0) {
      // Both scored (rare, usually end-of-period) — reset
      flush(play)
      runTeam = null
    }

    lastHome = play.scoreHome!
    lastAway = play.scoreAway!
  }

  flush(scored[scored.length - 1])
  return runs
}
