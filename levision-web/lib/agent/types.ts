import type { ChatMessage } from '@/lib/chat/types'

export type AgentOutcome =
  | { kind: 'answer'; answer: string }
  | { kind: 'no_match' }
  | { kind: 'error'; error: string }

export type AgentContext = {
  messages: ChatMessage[]
  latestUserText: string
}
