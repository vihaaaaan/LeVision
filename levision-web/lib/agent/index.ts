import { createOpenAI } from '@ai-sdk/openai'
import { stepCountIs } from 'ai'
import type { GameContext } from '@/lib/chat/types'
import { buildNbaTools } from './tools'
import { buildSystemPrompt } from './system-prompt'

export { buildNbaTools, buildSystemPrompt }
export type { GameContext }

export function buildAgentConfig(gameContext?: GameContext) {
  const apiKey = process.env.LEVISION_AGENT_OPENAI_API_KEY
  if (!apiKey) return null

  const openai = createOpenAI({ apiKey })
  return {
    model: openai('gpt-4o'),
    system: buildSystemPrompt(gameContext),
    tools: buildNbaTools(),
    stopWhen: stepCountIs(6),
  }
}
