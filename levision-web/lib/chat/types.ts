export type ChatRole = 'system' | 'user' | 'assistant'

export type ChatMessage = {
  role: ChatRole
  content: string
}

export type GameContext = {
  homeTeamId?: string
  awayTeamId?: string
  homeTeamName?: string
  awayTeamName?: string
  gameDate?: string
  espnEventId?: string
  title?: string
  clock?: string
  period?: number
  homeScore?: number
  awayScore?: number
  // live footage context
  onCourtHome?: string[]
  onCourtAway?: string[]
  recentEvents?: string[]
}

export type ChatRequest = {
  messages: ChatMessage[]
  gameContext?: GameContext
}

export type ChatResponse = {
  message: ChatMessage
  provider: 'stub' | 'custom-api' | 'openai' | 'nba-tools' | 'house-rules' | 'agent'
}
