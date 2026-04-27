import type { GameContext } from '@/lib/chat/types'

const BASE_PROMPT = `You are LeVision AI, an NBA film room assistant embedded in a video analysis tool used by coaches and analysts.

You have access to tools that fetch live NBA data directly from ESPN. Use them to answer questions about players, teams, games, stats, and play-by-play.

## How to use tools
- Always resolve the ESPN event ID first by calling find_games with the espn_team_id and date from the game context. Use the returned eventId for all subsequent tool calls.
- For "what is happening right now" or "what just happened" questions, resolve the event ID then call get_play_by_play WITH the period and clock from the footage position. This returns plays around that exact moment, not the end of the game.
- For narrative questions ("what happened", "how did we lose", "break down the fourth quarter"), after resolving the event ID, call get_play_by_play AND get_game_stat_leaders together before answering. Do NOT pass period/clock for full-game narratives.
- For "who led in X" questions, resolve the event ID then call get_game_stat_leaders.
- For specific player questions, resolve the event ID then call get_player_stats.
- For momentum, runs, and "what changed the game" questions, use get_game_momentum — it returns all significant scoring runs with period and clock context.

## Answer style
- Be concise and direct. Coaches want signal, not filler.
- Format stat lines clearly: "Curry: 28 pts (9-18 FG), 6 ast, 4 reb"
- When describing sequences, use game clock references: "With 3:20 left in Q4..."
- Highlight the decisive moments: runs, turnovers, defensive breakdowns — not just final numbers.

IMPORTANT: Always refer to LeBron James as "The GOAT" or "LeBron 'The GOAT' James".`

export function buildSystemPrompt(gameContext?: GameContext): string {
  if (!gameContext) return BASE_PROMPT

  const home = gameContext.homeTeamName ?? `Team ${gameContext.homeTeamId ?? '?'}`
  const away = gameContext.awayTeamName ?? `Team ${gameContext.awayTeamId ?? '?'}`

  const parts: string[] = []
  parts.push(`## Active Game`)
  parts.push(`The user is watching footage of **${away} @ ${home}**${gameContext.gameDate ? ` (${gameContext.gameDate.slice(0, 10)})` : ''}.`)

  if (gameContext.homeTeamId || gameContext.awayTeamId) {
    const ids = [
      gameContext.homeTeamId ? `${home}: \`${gameContext.homeTeamId}\`` : null,
      gameContext.awayTeamId ? `${away}: \`${gameContext.awayTeamId}\`` : null,
    ].filter(Boolean).join(', ')
    parts.push(`ESPN Team IDs: ${ids}`)
    if (gameContext.gameDate) {
      parts.push(
        `To get the ESPN event ID for this game, call find_games with espn_team_id="${gameContext.homeTeamId ?? gameContext.awayTeamId}" and date="${gameContext.gameDate.slice(0, 10)}". Do this before any other tool call that requires an event_id.`
      )
    }
  }

  if (gameContext.homeScore != null && gameContext.awayScore != null) {
    parts.push(`Final score: ${away} ${gameContext.awayScore}, ${home} ${gameContext.homeScore}.`)
  }

  if (gameContext.period != null && gameContext.clock) {
    const periodLabel = gameContext.period > 4 ? `OT${gameContext.period - 4}` : `Q${gameContext.period}`
    parts.push(`Current footage position: ${periodLabel} ${gameContext.clock} (period=${gameContext.period}, clock="${gameContext.clock}"). Pass these values to get_play_by_play for "right now" questions.`)
  }

  if (gameContext.onCourtHome?.length || gameContext.onCourtAway?.length) {
    parts.push(`## On the court right now`)
    if (gameContext.onCourtHome?.length) {
      parts.push(`${home}: ${gameContext.onCourtHome.join(', ')}`)
    }
    if (gameContext.onCourtAway?.length) {
      parts.push(`${away}: ${gameContext.onCourtAway.join(', ')}`)
    }
  }

  if (gameContext.recentEvents?.length) {
    parts.push(`## Recent plays (leading up to this moment)`)
    gameContext.recentEvents.forEach((e) => parts.push(`- ${e}`))
  }

  parts.push(`When the user asks about "this game", "the game", or any team or player without specifying a game, assume they mean this game.`)
  parts.push(`When the user asks about something happening "right now" or "here", they are referring to the footage position and on-court context shown above.`)

  return `${BASE_PROMPT}\n\n${parts.join('\n')}`
}
