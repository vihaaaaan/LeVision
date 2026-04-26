type Controller = ReadableStreamDefaultController<Uint8Array>

const registry = new Map<string, Set<Controller>>()
const encoder = new TextEncoder()

export function register(userId: string, ctrl: Controller): void {
  if (!registry.has(userId)) registry.set(userId, new Set())
  registry.get(userId)!.add(ctrl)
}

export function unregister(userId: string, ctrl: Controller): void {
  registry.get(userId)?.delete(ctrl)
  if (registry.get(userId)?.size === 0) registry.delete(userId)
}

export function emitToUser(userId: string, data: object): void {
  const controllers = registry.get(userId)
  if (!controllers) return
  const chunk = encoder.encode(`data: ${JSON.stringify(data)}\n\n`)
  for (const ctrl of controllers) {
    try { ctrl.enqueue(chunk) } catch { /* controller closed */ }
  }
}
