'use client'

import type { FootageClip } from '@/lib/footage-library'

function formatClipDate(value?: string) {
  if (!value) return 'No timestamp'

  const parsed = new Date(value)

  if (Number.isNaN(parsed.getTime())) {
    return value
  }

  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export default function GameTimeStatsPanel({ clip }: { clip: FootageClip | null }) {
  const hasClip = Boolean(clip)

  const statItems = hasClip
    ? [
        { label: 'Game Clock', value: '32:18', tone: 'text-offwhite' },
        { label: 'Quarter', value: 'Q3', tone: 'text-brand' },
        { label: 'Pace', value: '98.4', tone: 'text-offwhite' },
        { label: 'Shot Quality', value: 'B+', tone: 'text-brand' },
      ]
    : [
        { label: 'Game Clock', value: '--:--', tone: 'text-muted' },
        { label: 'Quarter', value: '--', tone: 'text-muted' },
        { label: 'Pace', value: '--', tone: 'text-muted' },
        { label: 'Shot Quality', value: '--', tone: 'text-muted' },
      ]

  return (
    <aside className="relative flex h-full min-h-[min(60vh,520px)] flex-col overflow-hidden rounded-sm border border-[rgba(200,136,58,0.24)] bg-[rgba(9,11,14,0.94)] shadow-[0_18px_55px_rgba(0,0,0,0.32)] backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-0 opacity-90">
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(200,136,58,0.95),transparent)]" />
        <div className="absolute -left-10 top-8 h-24 w-24 rounded-full bg-brand/12 blur-3xl" />
        <div className="absolute -right-14 bottom-10 h-28 w-28 rounded-full bg-brand/10 blur-3xl" />
      </div>

      <div className="relative flex h-full flex-col">
        <div className="border-b border-white/8 px-4 py-4">
          <p className="font-display text-[0.98rem] tracking-[0.12em] text-offwhite">
            GAME-TIME STATS
          </p>
          <p className="mt-1 text-[0.62rem] uppercase tracking-[0.2em] text-muted">
            Live coach snapshot
          </p>
        </div>

        <div className="flex flex-1 flex-col gap-4 px-4 py-4">
          <div className="grid grid-cols-2 gap-2">
            {statItems.map((item) => (
              <div
                key={item.label}
                className="rounded-[16px] border border-white/8 bg-white/[0.04] px-3 py-3"
              >
                <p className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">
                  {item.label}
                </p>
                <p className={`mt-1 font-display text-[1.05rem] tracking-[0.08em] ${item.tone}`}>
                  {item.value}
                </p>
              </div>
            ))}
          </div>

          <div className="rounded-[18px] border border-white/8 bg-white/[0.04] px-4 py-4">
            <p className="text-[0.58rem] uppercase tracking-[0.18em] text-muted">
              Active Clip
            </p>
            <p className="mt-2 font-display text-[0.98rem] leading-5 tracking-[0.08em] text-offwhite">
              {clip?.title ?? 'No clip loaded'}
            </p>
            <p className="mt-2 text-[0.72rem] leading-5 text-muted">
              {clip
                ? `Processed footage from ${formatClipDate(clip.createdAt)}.`
                : 'Load a processed clip to populate scouting context and possession timing.'}
            </p>
          </div>

          <div className="rounded-[18px] border border-dashed border-brand/25 bg-brand/5 px-4 py-4">
            <p className="text-[0.58rem] uppercase tracking-[0.18em] text-brand/75">
              Coach Note
            </p>
            <p className="mt-2 text-[0.74rem] leading-6 text-offwhite/80">
              Use this rail for scoreboard data, lineup splits, or possession tags once your
              playback pipeline starts returning event metadata.
            </p>
          </div>
        </div>
      </div>
    </aside>
  )
}
