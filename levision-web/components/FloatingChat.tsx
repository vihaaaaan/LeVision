'use client'

import { useState } from 'react'
import { useChatDock } from '@/components/chat/ChatDockProvider'
import LeVisionChatPanel from '@/components/chat/LeVisionChatPanel'
import { useLeVisionChat } from '@/hooks/useLeVisionChat'

export default function FloatingChat() {
  const { floatingHidden } = useChatDock()
  const [isOpen, setIsOpen] = useState(false)
  const { endRef, error, input, isSending, messages, setInput, submitMessage } =
    useLeVisionChat()

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    await submitMessage()
  }

  function handleComposerKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()

      void submitMessage()
    }
  }

  if (floatingHidden) {
    return null
  }

  return (
    <div className="pointer-events-none fixed inset-y-0 right-0 z-50 flex items-center">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        aria-expanded={isOpen}
        aria-controls="levision-chat-panel"
        className={`pointer-events-auto group absolute right-0 top-1/2 flex -translate-y-1/2 translate-x-[1px] items-center gap-3 rounded-l-[22px] border border-r-0 border-[rgba(200,136,58,0.32)] bg-[linear-gradient(180deg,rgba(19,22,27,0.96),rgba(9,11,14,0.96))] px-4 py-5 text-offwhite shadow-[0_18px_50px_rgba(0,0,0,0.35)] backdrop-blur-md transition-[right,background-color] duration-300 cursor-pointer ${
          isOpen ? 'right-[min(24rem,calc(100vw-2rem))]' : 'right-0'
        }`}
      >
        <span className="absolute inset-y-3 left-0 w-px bg-[linear-gradient(180deg,transparent,rgba(200,136,58,0.95),transparent)]" />
        <span className="absolute inset-x-3 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(200,136,58,0.5),transparent)]" />
        <span className="flex flex-col items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-brand shadow-[0_0_14px_rgba(200,136,58,0.9)]" />
          <span className="[writing-mode:vertical-rl] rotate-180 font-display text-[0.82rem] tracking-[0.22em]">
            {isOpen ? 'CLOSE CHAT' : 'OPEN CHAT'}
          </span>
        </span>
      </button>

      <section
        aria-hidden={!isOpen}
        className={`relative h-full w-[min(24rem,calc(100vw-2rem))] overflow-hidden border-l border-[rgba(200,136,58,0.24)] bg-[rgba(9,11,14,0.94)] shadow-[-24px_0_90px_rgba(0,0,0,0.45)] backdrop-blur-xl transition-transform duration-300 ${
          isOpen ? 'translate-x-0 pointer-events-auto' : 'translate-x-full pointer-events-none'
        }`}
      >
        <LeVisionChatPanel
          endRef={endRef}
          error={error}
          input={input}
          isSending={isSending}
          messages={messages}
          onClose={() => setIsOpen(false)}
          onInputChange={setInput}
          onKeyDown={handleComposerKeyDown}
          onSubmit={handleSubmit}
        />
      </section>
    </div>
  )
}
