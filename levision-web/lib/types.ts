export type Profile = {
  id: string
  email: string | null
  role: 'coach' | 'player' | 'analyst' | null
  onboarding_complete: boolean
  onboarding_step: number
  created_at: string
}

export type Game = {
  id: string
  homeTeam: string
  awayTeam: string
  homeScore: number
  awayScore: number
  date: string
  videoUrl?: string
  stats?: {
    homePoints: number
    awayPoints: number
    homeRebounds: number
    awayRebounds: number
    homeAssists: number
    awayAssists: number
    homeSteals: number
    awaySteals: number
    homeBlocks: number
    awayBlocks: number
    homeTurnovers: number
    awayTurnovers: number
    homeFouls: number
    awayFouls: number
    homeFgMade: number
    awayFgMade: number
    homeFgAttempted: number
    awayFgAttempted: number
    homeThreeMade: number
    awayThreeMade: number
    homeThreeAttempted: number
    awayThreeAttempted: number
    homeFtMade: number
    awayFtMade: number
    homeFtAttempted: number
    awayFtAttempted: number
    players?: {
      home: PlayerStats[]
      away: PlayerStats[]
    }
  }
}

export type PlayerStats = {
  name: string
  points: number
  rebounds: number
  assists: number
  minutes: number
}
