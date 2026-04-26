import { createClient } from '@/lib/supabase/server'
import { register, unregister } from '@/lib/events'

export const runtime = 'nodejs'

export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return new Response('Unauthorized', { status: 401 })

  const encoder = new TextEncoder()
  let ctrl: ReadableStreamDefaultController<Uint8Array>
  let pingInterval: ReturnType<typeof setInterval>

  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      ctrl = c
      register(user.id, c)
      pingInterval = setInterval(() => {
        try {
          c.enqueue(encoder.encode(`data: {"type":"ping"}\n\n`))
        } catch {
          clearInterval(pingInterval)
        }
      }, 25000)
    },
    cancel() {
      clearInterval(pingInterval)
      unregister(user.id, ctrl)
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  })
}
