import type { Game } from './types'

export type FootageClip = {
  id: string
  title: string
  createdAt?: string
  playbackUrl: string | null
  game?: Game
  visionStatus?: string
  visionStage?: string | null
  visionResultsKey?: string | null
  homeTeamId?: string
  awayTeamId?: string
  gameDate?: string | null
  espnGameId?: string | null
}

type FootageRow = {
  id: string
  filename: string
  r2_url: string | null
  espn_game_id: string | null
  home_team_id: string | null
  away_team_id: string | null
  game_date: string | null
  game_season: string | null
  vision_status: string
  vision_stage: string | null
  vision_results_key: string | null
  created_at: string
}

export async function fetchFootageLibraryClips(): Promise<FootageClip[]> {
  const res = await fetch('/api/footage')
  if (!res.ok) throw new Error('Failed to load footage')
  const data = (await res.json()) as { footage?: FootageRow[]; error?: string }
  if (data.error) throw new Error(data.error)

  return (data.footage ?? [])
    .filter((row) => row.vision_status === 'completed')
    .map((row) => ({
      id: row.id,
      title: row.filename,
      createdAt: row.created_at,
      playbackUrl: row.r2_url,
      visionStatus: row.vision_status,
      visionStage: row.vision_stage,
      visionResultsKey: row.vision_results_key,
      homeTeamId: row.home_team_id ?? undefined,
      awayTeamId: row.away_team_id ?? undefined,
      gameDate: row.game_date,
      espnGameId: row.espn_game_id,
    }))
}

export async function fetchAllFootage(): Promise<FootageRow[]> {
  const res = await fetch('/api/footage')
  if (!res.ok) throw new Error('Failed to load footage')
  const data = (await res.json()) as { footage?: FootageRow[]; error?: string }
  return data.footage ?? []
}
