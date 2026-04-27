import { tool } from 'ai'
import { z } from 'zod'
import {
  fetchScoreboard,
  fetchGameSummary,
  findTeamGamesOnScoreboard,
  findGameByTeamAndDate,
  parseGameSummary,
  parsePlayByPlay,
  computeMomentumRuns,
} from './espn'

const TEAM_ALIASES: Record<string, string> = {
  hawks: 'ATL', atlanta: 'ATL', atl: 'ATL',
  celtics: 'BOS', boston: 'BOS', bos: 'BOS', celts: 'BOS',
  nets: 'BKN', brooklyn: 'BKN', bkn: 'BKN',
  hornets: 'CHA', charlotte: 'CHA', cha: 'CHA',
  bulls: 'CHI', chicago: 'CHI', chi: 'CHI',
  cavaliers: 'CLE', cavs: 'CLE', cleveland: 'CLE', cle: 'CLE',
  mavericks: 'DAL', mavs: 'DAL', dallas: 'DAL', dal: 'DAL',
  nuggets: 'DEN', denver: 'DEN', den: 'DEN',
  pistons: 'DET', detroit: 'DET', det: 'DET',
  warriors: 'GSW', 'golden state': 'GSW', gsw: 'GSW', dubs: 'GSW',
  rockets: 'HOU', houston: 'HOU', hou: 'HOU',
  pacers: 'IND', indiana: 'IND', ind: 'IND',
  clippers: 'LAC', 'la clippers': 'LAC', lac: 'LAC', clips: 'LAC',
  lakers: 'LAL', 'la lakers': 'LAL', lal: 'LAL', 'los angeles lakers': 'LAL',
  grizzlies: 'MEM', memphis: 'MEM', mem: 'MEM', grizz: 'MEM',
  heat: 'MIA', miami: 'MIA', mia: 'MIA',
  bucks: 'MIL', milwaukee: 'MIL', mil: 'MIL',
  timberwolves: 'MIN', minnesota: 'MIN', min: 'MIN', wolves: 'MIN', twolves: 'MIN',
  pelicans: 'NOP', 'new orleans': 'NOP', nop: 'NOP', pels: 'NOP',
  knicks: 'NYK', 'new york': 'NYK', nyk: 'NYK',
  thunder: 'OKC', 'oklahoma city': 'OKC', okc: 'OKC',
  magic: 'ORL', orlando: 'ORL', orl: 'ORL',
  '76ers': 'PHI', sixers: 'PHI', philadelphia: 'PHI', phi: 'PHI', philly: 'PHI',
  suns: 'PHX', phoenix: 'PHX', phx: 'PHX',
  'trail blazers': 'POR', trailblazers: 'POR', blazers: 'POR', portland: 'POR', por: 'POR',
  kings: 'SAC', sacramento: 'SAC', sac: 'SAC',
  spurs: 'SAS', 'san antonio': 'SAS', sas: 'SAS',
  raptors: 'TOR', toronto: 'TOR', tor: 'TOR',
  jazz: 'UTA', utah: 'UTA', uta: 'UTA',
  wizards: 'WAS', washington: 'WAS', was: 'WAS',
}

function resolveAbbr(team: string): string {
  const lower = team.trim().toLowerCase()
  return TEAM_ALIASES[lower] ?? team.toUpperCase()
}

function todayEastern(): string {
  return new Date(
    new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })
  )
    .toISOString()
    .slice(0, 10)
}

function daysBack(n: number): string[] {
  const dates: string[] = []
  const base = new Date(
    new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })
  )
  for (let i = 0; i <= n; i++) {
    const d = new Date(base)
    d.setDate(d.getDate() - i)
    dates.push(d.toISOString().slice(0, 10))
  }
  return dates
}

function isFinal(status: string): boolean {
  const s = status.toLowerCase()
  return s.includes('final') || s === 'post' || s === 'completed' || s === 'status_final'
}

export function buildNbaTools() {
  return {
    find_games: tool({
      description:
        'Find NBA games for a team. Use this to resolve a game reference into an ESPN event_id. For recent games (within ~3 weeks) searches the scoreboard. For historical dates, provide espn_team_id (from game context) to use the season schedule instead.',
      inputSchema: z.object({
        team: z.string().describe('Team name or abbreviation, e.g. "Lakers", "GSW", "Boston Celtics"'),
        date: z.string().optional().describe('Specific date YYYY-MM-DD. Omit to search recent games.'),
        espn_team_id: z.string().optional().describe('ESPN team ID from the game context (homeTeamId or awayTeamId). Use this for historical dates older than 3 weeks.'),
        n: z.number().int().min(1).max(10).optional().describe('Max games to return (default 3)'),
      }),
      execute: async ({ team, date, espn_team_id, n = 3 }: { team: string; date?: string; espn_team_id?: string; n?: number }) => {
        try {
          // For historical dates with a known ESPN team ID, use the schedule endpoint
          if (date && espn_team_id) {
            const daysDiff = (Date.now() - new Date(date).getTime()) / (1000 * 60 * 60 * 24)
            if (daysDiff > 14) {
              const game = await findGameByTeamAndDate(espn_team_id, date)
              if (game) return JSON.stringify([game])
              return JSON.stringify({ message: `No game found for team ${espn_team_id} on ${date} via schedule lookup` })
            }
          }

          // Recent games: use scoreboard
          const abbr = resolveAbbr(team)
          const datesToCheck = date ? [date] : daysBack(21)
          const results = []

          for (const d of datesToCheck) {
            if (results.length >= n) break
            try {
              const scoreboard = await fetchScoreboard(d)
              const games = findTeamGamesOnScoreboard(scoreboard, abbr)
              for (const g of games) {
                if (results.length >= n) break
                if (isFinal(g.status)) results.push(g)
              }
            } catch {
              // skip dates that fail
            }
          }

          return JSON.stringify(results.length > 0 ? results : { message: `No completed games found for ${team}` })
        } catch (err) {
          return JSON.stringify({ error: String(err) })
        }
      },
    }),

    get_game_details: tool({
      description:
        'Get full details for a specific NBA game: score, team stats (FG%, 3PT%, rebounds, assists, turnovers, fast break points, points in paint), and boxscore for all players.',
      inputSchema: z.object({
        event_id: z.string().describe('ESPN event ID'),
      }),
      execute: async ({ event_id }: { event_id: string }) => {
        try {
          const summary = await fetchGameSummary(event_id)
          const parsed = parseGameSummary(summary, event_id)
          return JSON.stringify(parsed)
        } catch (err) {
          return JSON.stringify({ error: String(err), event_id })
        }
      },
    }),

    get_player_stats: tool({
      description:
        'Get stats for a specific player in a specific game. Returns their full boxscore line (pts, reb, ast, stl, blk, to, fg, 3pt, ft, +/-).',
      inputSchema: z.object({
        event_id: z.string().describe('ESPN event ID'),
        player: z.string().describe('Player full name or common name, e.g. "LeBron James", "Curry"'),
      }),
      execute: async ({ event_id, player }: { event_id: string; player: string }) => {
        try {
          const summary = await fetchGameSummary(event_id)
          const parsed = parseGameSummary(summary, event_id)
          const query = player.toLowerCase()
          const match = parsed.players.find((p) =>
            p.name.toLowerCase().includes(query) ||
            query.split(' ').every((word: string) => p.name.toLowerCase().includes(word))
          )
          if (!match) {
            return JSON.stringify({ error: `Player "${player}" not found in game ${event_id}` })
          }
          return JSON.stringify(match)
        } catch (err) {
          return JSON.stringify({ error: String(err), event_id })
        }
      },
    }),

    get_game_stat_leaders: tool({
      description:
        'Get the top N players in a specific stat category for a game (e.g. top scorers, rebounders, assists leaders). Great for "who scored the most" type questions.',
      inputSchema: z.object({
        event_id: z.string().describe('ESPN event ID'),
        stat: z
          .enum(['points', 'rebounds', 'assists', 'steals', 'blocks', 'turnovers', 'plusMinus'])
          .describe('Stat to rank players by'),
        top_n: z.number().int().min(1).max(10).optional().describe('Number of leaders to return (default 5)'),
      }),
      execute: async ({ event_id, stat, top_n = 5 }: { event_id: string; stat: 'points' | 'rebounds' | 'assists' | 'steals' | 'blocks' | 'turnovers' | 'plusMinus'; top_n?: number }) => {
        try {
          const summary = await fetchGameSummary(event_id)
          const parsed = parseGameSummary(summary, event_id)
          const active = parsed.players.filter((p) => !p.didNotPlay)
          const sorted = [...active].sort((a, b) => {
            const av = (a[stat as keyof typeof a] as number | null) ?? -999
            const bv = (b[stat as keyof typeof b] as number | null) ?? -999
            return bv - av
          })
          return JSON.stringify({
            game: `${parsed.awayTeam.name} @ ${parsed.homeTeam.name} (${parsed.date})`,
            stat,
            leaders: sorted.slice(0, top_n).map((p, i) => ({
              rank: i + 1,
              name: p.name,
              team: p.teamAbbr,
              value: p[stat as keyof typeof p],
            })),
          })
        } catch (err) {
          return JSON.stringify({ error: String(err), event_id })
        }
      },
    }),

    get_play_by_play: tool({
      description:
        'Get play-by-play for a game. Returns up to last_n plays in chronological order. Use for questions about what happened in the game, specific moments, or final minutes.',
      inputSchema: z.object({
        event_id: z.string().describe('ESPN event ID'),
        last_n: z
          .number()
          .int()
          .min(1)
          .max(75)
          .optional()
          .describe('Number of plays to return, from the end of the game (default 50)'),
      }),
      execute: async ({ event_id, last_n = 50 }: { event_id: string; last_n?: number }) => {
        try {
          const summary = await fetchGameSummary(event_id)
          const plays = parsePlayByPlay(summary, 500)
          const slice = plays.slice(-last_n)
          return JSON.stringify({ event_id, total_plays: plays.length, plays: slice })
        } catch (err) {
          return JSON.stringify({ error: String(err), event_id })
        }
      },
    }),

    get_game_momentum: tool({
      description:
        'Identify scoring runs and momentum shifts in a game. Returns all runs where one team scored 7+ consecutive unanswered (or near-unanswered) points, with the period, clock range, and score context. Use this for questions about momentum, runs, "when did we take over", or "what changed the game".',
      inputSchema: z.object({
        event_id: z.string().describe('ESPN event ID'),
        min_run: z.number().int().min(4).max(20).optional().describe('Minimum points for a run to be reported (default 7)'),
      }),
      execute: async ({ event_id, min_run = 7 }: { event_id: string; min_run?: number }) => {
        try {
          const summary = await fetchGameSummary(event_id)
          const parsed = parseGameSummary(summary, event_id)
          const plays = parsePlayByPlay(summary, 9999)
          const runs = computeMomentumRuns(plays, parsed.homeTeam.name, parsed.awayTeam.name, min_run)
          return JSON.stringify({
            game: `${parsed.awayTeam.name} @ ${parsed.homeTeam.name} (${parsed.date})`,
            finalScore: `${parsed.awayTeam.name} ${parsed.awayTeam.score} - ${parsed.homeTeam.name} ${parsed.homeTeam.score}`,
            totalRuns: runs.length,
            runs,
          })
        } catch (err) {
          return JSON.stringify({ error: String(err), event_id })
        }
      },
    }),

    get_team_recent_games: tool({
      description:
        'Get a team\'s recent completed games with scores. Useful for win/loss streaks, recent form, or finding game IDs to look up in more detail.',
      inputSchema: z.object({
        team: z.string().describe('Team name or abbreviation'),
        n: z.number().int().min(1).max(10).optional().describe('Number of recent games (default 5)'),
      }),
      execute: async ({ team, n = 5 }: { team: string; n?: number }) => {
        try {
          const abbr = resolveAbbr(team)
          const results = []

          for (const d of daysBack(30)) {
            if (results.length >= n) break
            try {
              const scoreboard = await fetchScoreboard(d)
              const games = findTeamGamesOnScoreboard(scoreboard, abbr)
              for (const g of games) {
                if (results.length >= n) break
                if (isFinal(g.status)) results.push(g)
              }
            } catch {
              // skip
            }
          }

          return JSON.stringify(results.length > 0 ? results : { message: `No recent games found for ${team}` })
        } catch (err) {
          return JSON.stringify({ error: String(err) })
        }
      },
    }),
  }
}
