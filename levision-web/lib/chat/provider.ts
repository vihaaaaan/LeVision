import type { ChatMessage, ChatResponse } from '@/lib/chat/types'
import { runNbaToolQuery } from '@/lib/chat/nba-tools'

type CustomApiResponse =
  | { message?: string; content?: string }
  | { reply?: { message?: string; content?: string } }

type OpenAIChatCompletionResponse = {
  choices?: Array<{
    message?: {
      content?: string | null
    }
  }>
  error?: {
    message?: string
  }
}

const DEFAULT_FALLBACK =
  "The LeVision assistant scaffold is live. Point `LEVISION_CHAT_API_URL` at your own model endpoint when you're ready, and I'll start routing messages there."

function resolveAssistantText(payload: CustomApiResponse): string | null {
  if ('message' in payload && typeof payload.message === 'string') {
    return payload.message
  }

  if ('content' in payload && typeof payload.content === 'string') {
    return payload.content
  }

  if (
    'reply' in payload &&
    payload.reply &&
    typeof payload.reply === 'object'
  ) {
    if (typeof payload.reply.message === 'string') {
      return payload.reply.message
    }

    if (typeof payload.reply.content === 'string') {
      return payload.reply.content
    }
  }

  return null
}

export async function generateChatReply(
  messages: ChatMessage[]
): Promise<ChatResponse> {
  const latestUserMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'user')

  if (latestUserMessage?.content) {
    const toolOutcome = await runNbaToolQuery(latestUserMessage.content)

    if (toolOutcome.kind === 'answer') {
      return {
        provider: 'nba-tools',
        message: {
          role: 'assistant',
          content: toolOutcome.answer,
        },
      }
    }

    if (toolOutcome.kind === 'error') {
      return {
        provider: 'nba-tools',
        message: {
          role: 'assistant',
          content: `NBA data tools error: ${toolOutcome.error}`,
        },
      }
    }
  }

  const endpoint = process.env.LEVISION_CHAT_API_URL
  const customApiKey = process.env.LEVISION_CHAT_API_KEY
  const openAiApiKey = process.env.OPENAI_API_KEY ?? customApiKey
  const openAiModel = process.env.LEVISION_OPENAI_MODEL ?? 'gpt-5-nano'

  if (endpoint) {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(customApiKey ? { Authorization: `Bearer ${customApiKey}` } : {}),
      },
      body: JSON.stringify({
        messages,
        app: 'LeVision',
      }),
      cache: 'no-store',
    })

    if (!response.ok) {
      throw new Error(`Custom chat API returned ${response.status}`)
    }

    const payload = (await response.json()) as CustomApiResponse
    const content = resolveAssistantText(payload)

    if (!content) {
      throw new Error('Custom chat API response is missing assistant content')
    }

    return {
      provider: 'custom-api',
      message: {
        role: 'assistant',
        content,
      },
    }
  }

  if (!openAiApiKey) {
    return {
      provider: 'stub',
      message: {
        role: 'assistant',
        content: DEFAULT_FALLBACK,
      },
    }
  }

  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${openAiApiKey}`,
    },
    body: JSON.stringify({
      model: openAiModel,
      messages,
    }),
    cache: 'no-store',
  })

  const payload = (await response.json()) as OpenAIChatCompletionResponse

  if (!response.ok) {
    const details = payload.error?.message
      ? `: ${payload.error.message}`
      : ''
    throw new Error(`OpenAI returned ${response.status}${details}`)
  }

  const content = payload.choices?.[0]?.message?.content?.trim()

  if (!content) {
    throw new Error('OpenAI response is missing assistant content')
  }

  return {
    provider: 'openai',
    message: {
      role: 'assistant',
      content,
    },
  }
}
