import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export const runtime = 'nodejs'

type LinkGameBody = {
  espn_game_id: string
  home_team_id: string
  away_team_id: string
  game_date: string
  game_season: string
  game_venue?: string
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params

  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const body = (await request.json()) as LinkGameBody

  if (!body.espn_game_id || !body.home_team_id || !body.away_team_id || !body.game_date || !body.game_season) {
    return NextResponse.json(
      { error: 'espn_game_id, home_team_id, away_team_id, game_date, and game_season are required' },
      { status: 400 }
    )
  }

  // Fetch the footage row to get r2_key for the Modal trigger
  const { data: footage, error: fetchError } = await supabase
    .from('footage')
    .select('r2_key')
    .eq('id', id)
    .eq('uploaded_by', user.id)
    .single()

  if (fetchError || !footage) {
    return NextResponse.json({ error: 'Footage not found' }, { status: 404 })
  }

  // Write all structured game columns
  const { error: updateError } = await supabase
    .from('footage')
    .update({
      espn_game_id: body.espn_game_id,
      home_team_id: body.home_team_id,
      away_team_id: body.away_team_id,
      game_date: body.game_date,
      game_season: body.game_season,
      game_venue: body.game_venue ?? null,
      vision_status: 'processing',
      vision_stage: 'downloading',
    })
    .eq('id', id)
    .eq('uploaded_by', user.id)

  if (updateError) {
    return NextResponse.json({ error: updateError.message }, { status: 500 })
  }

  // Fire-and-forget Modal trigger
  const modalUrl = process.env.MODAL_TRIGGER_URL
  const appUrl = process.env.NEXT_PUBLIC_APP_URL
  const webhookSecret = process.env.VISION_WEBHOOK_SECRET

  if (modalUrl && appUrl && webhookSecret) {
    fetch(modalUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        clip_id: id,
        r2_key: footage.r2_key,
        home_team_id: body.home_team_id,
        away_team_id: body.away_team_id,
        game_date: body.game_date,
        webhook_url: `${appUrl}/api/vision/webhook`,
        secret: webhookSecret,
      }),
    }).catch((err) => console.error('Modal trigger failed', err))
  } else {
    console.warn('Modal not configured — skipping pipeline trigger (MODAL_TRIGGER_URL, NEXT_PUBLIC_APP_URL, VISION_WEBHOOK_SECRET required)')
  }

  return NextResponse.json({ ok: true })
}
