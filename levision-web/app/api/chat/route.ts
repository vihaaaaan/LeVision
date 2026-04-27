import { NextResponse } from 'next/server'
import { streamText, convertToModelMessages } from 'ai'
import { buildAgentConfig } from '@/lib/agent'
import { generateChatReply } from '@/lib/chat/provider'
import type { GameContext } from '@/lib/chat/types'

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      messages?: unknown[]
      gameContext?: GameContext
    }

    const rawMessages = Array.isArray(body.messages) ? body.messages : []

    if (rawMessages.length === 0) {
      return NextResponse.json(
        { error: 'At least one valid chat message is required.' },
        { status: 400 }
      )
    }

    const agentConfig = buildAgentConfig(body.gameContext)

    if (agentConfig) {
      console.log('[agent] gameContext:', JSON.stringify(body.gameContext ?? null))
      // v6: convert UIMessage[] → ModelMessage[] for streamText
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const modelMessages = await convertToModelMessages(rawMessages as any[])
      const result = streamText({
        ...agentConfig,
        messages: modelMessages,
        onStepFinish: (step) => {
          console.log('[agent] step finish reason:', step.finishReason)
          if (step.toolCalls?.length) {
            console.log('[agent] tool calls:', JSON.stringify(step.toolCalls.map(t => ({ name: t.toolName, input: t.input }))))
          }
          if (step.toolResults?.length) {
            console.log('[agent] tool results (first 300 chars):', JSON.stringify(step.toolResults.map(t => ({ name: t.toolName, result: String(t.output).slice(0, 300) }))))
          }
        },
      })
      return result.toUIMessageStreamResponse()
    }

    // Fallback: non-streaming JSON path (no agent API key configured)
    const legacyMessages = rawMessages.filter(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (m: any) => m && typeof m.content === 'string' && ['system', 'user', 'assistant'].includes(m.role)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ) as any[]
    if (legacyMessages.length === 0) {
      return NextResponse.json(
        { error: 'At least one valid chat message is required.' },
        { status: 400 }
      )
    }
    const reply = await generateChatReply(legacyMessages)
    return NextResponse.json(reply)
  } catch (error) {
    console.error('Chat route failed', error)
    return NextResponse.json(
      { error: 'Unable to generate a chat response right now.' },
      { status: 500 }
    )
  }
}
