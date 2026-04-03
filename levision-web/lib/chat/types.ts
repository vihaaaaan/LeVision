export type ChatRole = 'system' | 'user' | 'assistant'

export type ChatMessage = {
  role: ChatRole
  content: string
}

export type ChatRequest = {
  messages: ChatMessage[]
}

export type ChatResponse = {
  message: ChatMessage
  provider: 'stub' | 'custom-api' | 'openai' | 'nba-tools'
}
