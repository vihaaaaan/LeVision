'use client'

import type { Game } from '@/lib/types'
import { useState, useEffect } from 'react'
import Image from 'next/image'
import { createClient } from '@/lib/supabase/client'

type Props = {
  team: 'home' | 'away'
  game?: Game
}

export default function TeamStatsPanel({ team, game }: Props) {
  const isHome = team === 'home'
  
  // Track which player images have failed to load
  const [failedImages, setFailedImages] = useState<Set<string>>(new Set())
  // Store headshot URLs fetched from database
  const [headshots, setHeadshots] = useState<Record<string, string>>({})

  // Temporary fake player data for when no game data is available
  const fakePlayers = [
    { name: 'LeBron James', points: 28, rebounds: 10, assists: 8, minutes: 35 },
    { name: 'Anthony Davis', points: 25, rebounds: 12, assists: 3, minutes: 32 },
    { name: 'Austin Reaves', points: 18, rebounds: 5, assists: 6, minutes: 28 },
    { name: 'D\'Angelo Russell', points: 15, rebounds: 3, assists: 7, minutes: 30 },
    { name: 'Rui Hachimura', points: 12, rebounds: 8, assists: 2, minutes: 25 }
  ]

  const teamName = game ? (isHome ? game.homeTeam : game.awayTeam) : (isHome ? 'HOME TEAM' : 'AWAY TEAM')
  const stats = game?.stats || null

  const players = game?.stats?.players?.[team] || fakePlayers

  // Fetch headshots from Supabase when players change
  useEffect(() => {
    const fetchHeadshots = async () => {
      const supabase = createClient()
      const newHeadshots: Record<string, string> = {}
      
      for (const player of players) {
        try {
          const { data, error } = await supabase
            .from('players')
            .select('headshot_url')
            .eq('full_name', player.name)
            .single()
          
          if (!error && data?.headshot_url) {
            newHeadshots[player.name] = data.headshot_url
          }
        } catch (error) {
          // Silently continue if player not found
          console.warn(`Could not fetch headshot for ${player.name}:`, error)
        }
      }
      
      setHeadshots(newHeadshots)
    }

    if (players.length > 0) {
      fetchHeadshots()
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

  return (
    <aside className="relative flex h-full min-h-[min(60vh,520px)] flex-col overflow-hidden rounded-sm border border-[rgba(200,136,58,0.24)] bg-[rgba(9,11,14,0.94)] shadow-[0_18px_55px_rgba(0,0,0,0.32)] backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-0 opacity-90">
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(200,136,58,0.95),transparent)]" />
        <div className="absolute -left-10 top-8 h-24 w-24 rounded-full bg-brand/12 blur-3xl" />
        <div className="absolute -right-14 bottom-10 h-28 w-28 rounded-full bg-brand/10 blur-3xl" />
      </div>

      <div className="relative flex h-full flex-col">
        <div className="border-b border-white/8 px-4 py-4">
          <p className="font-display text-[0.98rem] tracking-[0.12em] text-offwhite">
            {teamName.toUpperCase()}
          </p>
          <p className="mt-1 text-[0.62rem] uppercase tracking-[0.2em] text-muted">
            Player Statistics
          </p>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
          {/* Player Stats - Vertical Stacking */}
          <div className="space-y-3">
            {players.map((player, index) => (
              <div key={index} className="rounded-[18px] border border-white/8 bg-white/[0.04] px-4 py-3">
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
                    <h4 className="font-display text-offwhite text-sm tracking-wide truncate">{formatPlayerName(player.name)}</h4>
                  </div>
                  
                  {/* Stats */}
                  <div className="flex items-center gap-3 text-center">
                    <div>
                      <div className="font-body text-offwhite text-sm font-bold">{player.points}</div>
                      <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">PTS</div>
                    </div>
                    <div>
                      <div className="font-body text-offwhite text-sm font-bold">{player.assists}</div>
                      <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">AST</div>
                    </div>
                    <div>
                      <div className="font-body text-offwhite text-sm font-bold">{player.rebounds}</div>
                      <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">REB</div>
                    </div>
                    <div>
                      <div className="font-body text-offwhite text-sm font-bold">{player.steals || 0}</div>
                      <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">STL</div>
                    </div>
                    <div>
                      <div className="font-body text-offwhite text-sm font-bold">{player.blocks || 0}</div>
                      <div className="text-[0.45rem] uppercase tracking-[0.15em] text-muted">BLK</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Team Summary */}
          {game?.stats && (
            <div className="rounded-[18px] border border-white/8 bg-white/[0.04] px-4 py-4">
              <p className="text-[0.58rem] uppercase tracking-[0.18em] text-muted mb-3">
                Team Summary
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{stats.homePoints + stats.awayPoints}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Total PTS</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{stats.homeRebounds + stats.awayRebounds}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Total REB</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{stats.homeAssists + stats.awayAssists}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Total AST</div>
                </div>
                <div className="text-center">
                  <div className="font-body text-offwhite text-sm">{players.length}</div>
                  <div className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">Players</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}