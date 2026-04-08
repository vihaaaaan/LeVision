'use client'

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

type ChatDockContextValue = {
  floatingHidden: boolean
  setFloatingHidden: (hidden: boolean) => void
}

const ChatDockContext = createContext<ChatDockContextValue | null>(null)

export function ChatDockProvider({ children }: { children: ReactNode }) {
  const [floatingHidden, setFloatingHidden] = useState(false)

  const value = useMemo(
    () => ({ floatingHidden, setFloatingHidden }),
    [floatingHidden]
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
