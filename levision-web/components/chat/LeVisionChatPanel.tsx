'use client'

import type { RefObject } from 'react'
import type { ChatMessage } from '@/lib/chat/types'

type Props = {
  endRef: RefObject<HTMLDivElement | null>
  error: string | null
  input: string
  isSending: boolean
  messages: ChatMessage[]
  onClose?: () => void
  onInputChange: (value: string) => void
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void
  variant?: 'drawer' | 'inline'
}

export default function LeVisionChatPanel({
  endRef,
  error,
  input,
  isSending,
  messages,
  onClose,
  onInputChange,
  onKeyDown,
  onSubmit,
  variant = 'drawer',
}: Props) {
  const isInline = variant === 'inline'
  const shellClass = isInline
    ? 'flex h-full min-h-[min(60vh,520px)] flex-col rounded-sm border border-[rgba(200,136,58,0.24)] shadow-[0_18px_55px_rgba(0,0,0,0.32)]'
    : 'h-full border-l border-[rgba(200,136,58,0.24)] shadow-[-24px_0_90px_rgba(0,0,0,0.45)]'
  const titleClass = isInline
    ? 'font-display text-[0.98rem] tracking-[0.12em] text-offwhite'
    : 'font-display text-[1.1rem] tracking-[0.12em] text-offwhite'
  const subtitleClass = isInline
    ? 'mt-1 text-[0.62rem] uppercase tracking-[0.2em] text-muted'
    : 'mt-1 text-[0.68rem] uppercase tracking-[0.22em] text-muted'
  const bubbleClass = isInline
    ? 'max-w-[88%] rounded-[18px] px-3 py-2.5 text-[0.72rem] leading-5 shadow-[0_10px_35px_rgba(0,0,0,0.2)]'
    : 'max-w-[86%] rounded-2xl px-4 py-3 text-[0.82rem] leading-6 shadow-[0_10px_35px_rgba(0,0,0,0.2)]'
  const textareaClass = isInline
    ? 'w-full resize-none rounded-[16px] border border-white/10 bg-white/[0.04] px-3 py-2.5 pr-14 text-[0.78rem] leading-5 text-offwhite outline-none transition-colors duration-200 placeholder:text-white/25 focus:border-brand focus:bg-brand/5'
    : 'w-full resize-none rounded-[18px] border border-white/10 bg-white/[0.04] px-4 py-3 pr-14 text-sm text-offwhite outline-none transition-colors duration-200 placeholder:text-white/25 focus:border-brand focus:bg-brand/5'

  return (
    <section
      id={isInline ? undefined : 'levision-chat-panel'}
      className={`relative overflow-hidden bg-[rgba(9,11,14,0.94)] backdrop-blur-xl ${shellClass}`}
    >
      <div className="pointer-events-none absolute inset-0 opacity-90">
        <div
          className={`absolute inset-y-0 left-0 w-px bg-[linear-gradient(180deg,transparent,rgba(200,136,58,0.95),transparent)] ${
            isInline ? 'hidden' : ''
          }`}
        />
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(200,136,58,0.95),transparent)]" />
        <div className="absolute -left-10 top-10 h-28 w-28 rounded-full bg-brand/15 blur-3xl" />
        <div className="absolute -right-16 bottom-10 h-32 w-32 rounded-full bg-brand/10 blur-3xl" />
      </div>

      <div className="relative flex h-full flex-col">
        <div className={`relative border-b border-white/8 ${isInline ? 'px-4 py-4' : 'px-5 py-4'}`}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className={titleClass}>LEVISION AI</p>
              <p className={subtitleClass}>
                {isInline ? 'Coach companion' : 'Custom model ready'}
              </p>
            </div>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close chatbot"
                className="text-muted transition-colors duration-200 hover:text-offwhite"
              >
                X
              </button>
            )}
          </div>
        </div>

        <div className={`relative min-h-0 flex-1 overflow-y-auto chat-scroll ${isInline ? 'px-3 py-3' : 'px-4 py-4'}`}>
          <div className={`flex flex-col ${isInline ? 'gap-2.5' : 'gap-3'}`}>
            {messages.map((message, index) => {
              const isUser = message.role === 'user'

              return (
                <div
                  key={`${message.role}-${index}-${message.content.slice(0, 16)}`}
                  className={`${bubbleClass} ${
                    isUser
                      ? 'ml-auto rounded-br-sm bg-brand text-pitch'
                      : 'rounded-bl-sm border border-white/8 bg-white/[0.04] text-offwhite'
                  }`}
                >
                  {message.content}
                </div>
              )
            })}

            {isSending && (
              <div className={`${bubbleClass} rounded-bl-sm border border-white/8 bg-white/[0.04] text-offwhite`}>
                <span className="flex items-center gap-1.5 text-muted">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand [animation-delay:120ms]" />
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand [animation-delay:240ms]" />
                </span>
              </div>
            )}

            <div ref={endRef} />
          </div>
        </div>

        <form onSubmit={onSubmit} className={`relative border-t border-white/8 ${isInline ? 'px-3 py-3' : 'px-4 py-4'}`}>
          <label htmlFor={isInline ? 'coach-chat-input' : 'chat-input'} className="sr-only">
            Message LeVision AI
          </label>
          <textarea
            id={isInline ? 'coach-chat-input' : 'chat-input'}
            rows={3}
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask LeVision about your game, scouting, or workflow..."
            className={textareaClass}
          />

          <button
            type="submit"
            disabled={isSending || input.trim().length === 0}
            aria-label="Send message"
            className={`absolute flex items-center justify-center rounded-full bg-brand text-pitch transition-colors duration-200 hover:bg-brand-light disabled:cursor-not-allowed disabled:opacity-40 ${
              isInline ? 'bottom-6 right-6 h-9 w-9 text-[0.68rem]' : 'bottom-7 right-7 h-10 w-10'
            }`}
          >
            GO
          </button>

          <div className="mt-3 flex items-center justify-between gap-3">
            <p className={`${isInline ? 'text-[0.58rem]' : 'text-[0.65rem]'} uppercase tracking-[0.18em] text-muted`}>
              Endpoint: {process.env.NEXT_PUBLIC_LEVISION_CHAT_LABEL ?? 'scaffold'}
            </p>
            {error && <p className={`${isInline ? 'text-[0.66rem]' : 'text-[0.72rem]'} text-accent`}>{error}</p>}
          </div>
        </form>
      </div>
    </section>
  )
}
