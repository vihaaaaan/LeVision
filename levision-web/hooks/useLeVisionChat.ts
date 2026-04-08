'use client'

import { useEffect, useRef, useState } from 'react'
import type { ChatMessage, ChatResponse } from '@/lib/chat/types'

const INITIAL_MESSAGE: ChatMessage = {
  role: 'assistant',
  content:
    'Film room is open. Ask about coverages, player trends, or wire this panel to your own model endpoint when you are ready.',
}

export function useLeVisionChat() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([INITIAL_MESSAGE])
  const [isSending, setIsSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function submitMessage() {
    const trimmed = input.trim()

    if (!trimmed || isSending) {
      return
    }

    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: 'user', content: trimmed },
    ]

    setMessages(nextMessages)
    setInput('')
    setError(null)
    setIsSending(true)

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: nextMessages,
        }),
      })

      if (!response.ok) {
        throw new Error('Request failed')
      }

      const payload = (await response.json()) as ChatResponse
      setMessages((current) => [...current, payload.message])
    } catch {
      setError('The assistant is unavailable right now. Try again in a moment.')
    } finally {
      setIsSending(false)
    }
  }

  return {
    endRef,
    error,
    input,
    isSending,
    messages,
    setInput,
    submitMessage,
  }
}
