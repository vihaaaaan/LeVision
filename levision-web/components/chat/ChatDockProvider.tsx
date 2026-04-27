'use client'

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { GameContext } from '@/lib/chat/types'

type ChatDockContextValue = {
  floatingHidden: boolean
  setFloatingHidden: (hidden: boolean) => void
  activeGameContext: GameContext | null
  setActiveGameContext: (ctx: GameContext | null) => void
}

const ChatDockContext = createContext<ChatDockContextValue | null>(null)

export function ChatDockProvider({ children }: { children: ReactNode }) {
  const [floatingHidden, setFloatingHidden] = useState(true)
  const [activeGameContext, setActiveGameContext] = useState<GameContext | null>(null)

  const value = useMemo(
    () => ({ floatingHidden, setFloatingHidden, activeGameContext, setActiveGameContext }),
    [floatingHidden, activeGameContext]
  )

  return (
    <ChatDockContext.Provider value={value}>{children}</ChatDockContext.Provider>
  )
}

export function useChatDock() {
  const context = useContext(ChatDockContext)

  if (!context) {
    throw new Error('useChatDock must be used within ChatDockProvider')
  }

  return context
}
