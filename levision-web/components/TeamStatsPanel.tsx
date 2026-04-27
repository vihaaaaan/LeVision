'use client'

import type { Game, LiveTeamState } from '@/lib/types'
import { useState, useEffect, useMemo } from 'react'
import Image from 'next/image'
import { createClient } from '@/lib/supabase/client'
import StatBurst from '@/components/StatBurst'

type DisplayPlayer = {
  name: string
  points: number
  rebounds: number
  assists: number
  steals?: number
  blocks?: number
  minutes?: number
  onCourt?: boolean
  liveId?: string
}

type Props = {
  team: 'home' | 'away'
  game?: Game
  liveTeam?: LiveTeamState
  liveClock?: string
  livePeriod?: number
}

function formatQuarter(period?: number): string {
  if (!period || period <= 0) return ''
  if (period > 4) return `OT${period - 4}`
  return `Q${period}`
}

export default function TeamStatsPanel({
  team,
  game,
  liveTeam,
  liveClock,
  livePeriod,
}: Props) {
  const isHome = team === 'home'

  // Track which player images have failed to load
  const [failedImages, setFailedImages] = useState<Set<string>>(new Set())
  // Store headshot URLs fetched from database
  const [headshots, setHeadshots] = useState<Record<string, string>>({})

  const handleImageError = (name: string) => {
    setFailedImages((prev) => {
      if (prev.has(name)) return prev
      const next = new Set(prev)
      next.add(name)
      return next
    })
  }

  // Temporary fake player data for when no game data is available
  const fakePlayers: DisplayPlayer[] = [
    { name: 'LeBron James', points: 28, rebounds: 10, assists: 8, minutes: 35 },
    { name: 'Anthony Davis', points: 25, rebounds: 12, assists: 3, minutes: 32 },
    { name: 'Austin Reaves', points: 18, rebounds: 5, assists: 6, minutes: 28 },
    { name: 'D\'Angelo Russell', points: 15, rebounds: 3, assists: 7, minutes: 30 },
    { name: 'Rui Hachimura', points: 12, rebounds: 8, assists: 2, minutes: 25 }
  ]

  const teamName = liveTeam
    ? liveTeam.teamName
    : game
      ? (isHome ? game.homeTeam : game.awayTeam)
      : (isHome ? 'HOME TEAM' : 'AWAY TEAM')

  const stats = game?.stats || null

  const players = useMemo<DisplayPlayer[]>(() => {
    if (liveTeam) {
      return liveTeam.playerStats.map((p) => ({
        name: p.name,
        points: p.points,
        rebounds: p.rebounds,
        assists: p.assists,
        steals: p.steals,
        blocks: p.blocks,
        onCourt: p.onCourt,
        liveId: p.id,
      }))
    }
    return (game?.stats?.players?.[team] as DisplayPlayer[] | undefined) ?? fakePlayers
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveTeam, game, team])

  // Fetch headshots from Supabase when the roster changes. Uses a single
  // `IN (...)` query so the live path (13+ players per team) is one round-trip
  // instead of one per player.
  useEffect(() => {
    const names = Array.from(new Set(players.map((p) => p.name))).filter(Boolean)
    if (names.length === 0) return

    let cancelled = false
    const supabase = createClient()

    supabase
      .from('players')
      .select('full_name, headshot_url')
      .in('full_name', names)
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) {
          console.warn('Could not fetch headshots:', error)
          return
        }
        const next: Record<string, string> = {}
        for (const row of data ?? []) {
          if (row?.full_name && row?.headshot_url) {
            next[row.full_name] = row.headshot_url
          }
        }
        setHeadshots(next)
      })

    return () => {
      cancelled = true
    }
  }, [players])

  // Format player name as "First Initial. Last Name"
  const formatPlayerName = (fullName: string) => {
    const parts = fullName.trim().split(' ')
    if (parts.length < 2) return fullName
    const firstInitial = parts[0][0].toUpperCase()
    const lastName = parts[parts.length - 1]
    return `${firstInitial}. ${lastName}`
  }

  const showLiveHeader = Boolean(liveTeam)
  const quarterLabel = formatQuarter(livePeriod)

  return (
    <aside className="relative flex h-full flex-col overflow-hidden rounded-sm border border-[rgba(200,136,58,0.24)] bg-[rgba(9,11,14,0.94)] shadow-[0_18px_55px_rgba(0,0,0,0.32)] backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-0 opacity-90">
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(200,136,58,0.95),transparent)]" />
        <div className="absolute -left-10 top-8 h-24 w-24 rounded-full bg-brand/12 blur-3xl" />
        <div className="absolute -right-14 bottom-10 h-28 w-28 rounded-full bg-brand/10 blur-3xl" />
      </div>

      <div className="relative flex h-full flex-col">
        <div className="border-b border-white/8 px-4 py-4">
          <div className="flex items-center justify-between gap-2">
            <p className="font-display text-[0.98rem] tracking-[0.12em] text-offwhite">
              {teamName.toUpperCase()}
            </p>
            {showLiveHeader && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[0.55rem] font-semibold uppercase tracking-[0.18em] text-red-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
                Live
              </span>
            )}
          </div>
          <p className="mt-1 text-[0.62rem] uppercase tracking-[0.2em] text-muted">
            {showLiveHeader && (liveClock || quarterLabel)
              ? `${quarterLabel}${quarterLabel && liveClock ? ' · ' : ''}${liveClock ?? ''}`
              : 'Player Statistics'}
          </p>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
          {/* Player Stats - Vertical Stacking */}
          <div className="space-y-3">
            {players.map((player, index) => {
              const isOnCourt = Boolean(player.onCourt)
              const cardClasses = isOnCourt
                ? 'rounded-[18px] border border-brand/40 bg-brand/[0.08] px-4 py-3 shadow-[0_0_0_1px_rgba(200,136,58,0.15)]'
                : showLiveHeader
                  ? 'rounded-[18px] border border-white/6 bg-white/[0.02] px-4 py-3 opacity-70'
                  : 'rounded-[18px] border border-white/8 bg-white/[0.04] px-4 py-3'

              return (
                <div key={player.liveId ?? index} className={cardClasses}>
                  <div className="flex items-center gap-3">
                    {/* Player Image */}
                    <div className="w-10 h-10 rounded-full bg-brand/20 border border-brand/30 flex items-center justify-center flex-shrink-0 overflow-hidden">
                      {headshots[player.name] && !failedImages.has(player.name) ? (
                        <Image
                          src={headshots[player.name]}
                          alt={`${formatPlayerName(player.name)} headshot`}
                          width={40}
                          height={40}
                          className="w-full h-full object-cover rounded-full"
                          onError={() => handleImageError(player.name)}
                        />
                      ) : (
                        <span className="text-brand text-sm font-bold">
                          {player.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()}
                        </span>
                      )}
                    </div>

                    {/* Player Name */}
                    <div className="flex-1 min-w-0">
                      <h4 className="font-display text-offwhite text-sm tracking-wide truncate">
                        {formatPlayerName(player.name)}
                      </h4>
                      {showLiveHeader && (
                        <p className="mt-0.5 text-[0.52rem] uppercase tracking-[0.18em] text-muted">
                          {isOnCourt ? 'On Court' : 'Bench'}
                        </p>
                      )}
                    </div>

                    {/* Stats */}
                    <div className="flex items-center gap-3 text-center">
                      <div>
                        <div className="font-body text-offwhite text-sm font-bold"><StatBurst value={player.points}>{player.points}</StatBurst></div>
                        <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">PTS</div>
                      </div>
                      <div>
                        <div className="font-body text-offwhite text-sm font-bold"><StatBurst value={player.assists}>{player.assists}</StatBurst></div>
                        <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">AST</div>
                      </div>
                      <div>
                        <div className="font-body text-offwhite text-sm font-bold"><StatBurst value={player.rebounds}>{player.rebounds}</StatBurst></div>
                        <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">REB</div>
                      </div>
                      <div>
                        <div className="font-body text-offwhite text-sm font-bold"><StatBurst value={player.steals ?? 0}>{player.steals ?? 0}</StatBurst></div>
                        <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">STL</div>
                      </div>
                      <div>
                        <div className="font-body text-offwhite text-sm font-bold"><StatBurst value={player.blocks ?? 0}>{player.blocks ?? 0}</StatBurst></div>
                        <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">BLK</div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Team Summary */}
          {!liveTeam && game?.stats && (
            <div className="rounded-[18px] border border-white/8 bg-white/[0.04] px-4 py-4">
              <p className="text-[0.58rem] uppercase tracking-[0.18em] text-muted mb-3">
                Team Summary
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{stats!.homePoints + stats!.awayPoints}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Total PTS</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{stats!.homeRebounds + stats!.awayRebounds}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Total REB</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{stats!.homeAssists + stats!.awayAssists}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Total AST</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{players.length}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Players</div>
                </div>
              </div>
            </div>
          )}

          {liveTeam && (
            <div className="rounded-[18px] border border-white/8 bg-white/[0.04] px-4 py-4">
              <p className="text-[0.58rem] uppercase tracking-[0.18em] text-muted mb-3">
                Live Team Totals
              </p>
              <div className="grid grid-cols-3 gap-3">
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">
                    {liveTeam.playerStats.reduce((sum, p) => sum + p.points, 0)}
                  </div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">PTS</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">
                    {liveTeam.playerStats.reduce((sum, p) => sum + p.rebounds, 0)}
                  </div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">REB</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">
                    {liveTeam.playerStats.reduce((sum, p) => sum + p.assists, 0)}
                  </div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">AST</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
