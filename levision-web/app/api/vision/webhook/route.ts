import { NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'
import { emitToUser } from '@/lib/events'

export const runtime = 'nodejs'

function createServiceClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
  )
}

type WebhookBody = {
  event: 'stage_update' | 'completed' | 'failed'
  clip_id: string
  stage?: string
  results_key?: string
  error?: string
}

export async function POST(request: Request) {
  const secret = request.headers.get('x-vision-secret')
  if (!secret || secret !== process.env.VISION_WEBHOOK_SECRET) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const body = (await request.json()) as WebhookBody

  if (!body.clip_id || !body.event) {
    return NextResponse.json({ error: 'clip_id and event are required' }, { status: 400 })
  }

  const supabase = createServiceClient()

  let update: Record<string, unknown>
  if (body.event === 'stage_update') {
    update = { vision_stage: body.stage }
  } else if (body.event === 'completed') {
    update = {
      vision_status: 'completed',
      vision_stage: null,
      vision_results_key: body.results_key,
    }
  } else {
    update = {
      vision_status: 'failed',
      vision_stage: null,
      vision_error: body.error,
    }
  }

  const { data: footage, error } = await supabase
    .from('footage')
    .update(update)
    .eq('id', body.clip_id)
    .select('uploaded_by')
    .single()

  if (error || !footage) {
    return NextResponse.json({ error: 'Footage not found' }, { status: 404 })
  }

  emitToUser(footage.uploaded_by, {
    type: 'vision_update',
    clip_id: body.clip_id,
    event: body.event,
    stage: body.stage ?? null,
    results_key: body.results_key ?? null,
    error: body.error ?? null,
  })

  return NextResponse.json({ ok: true })
}
