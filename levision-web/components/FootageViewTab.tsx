import { useEffect, useMemo, useRef, useState } from 'react'
import GameTimeStatsPanel from '@/components/GameTimeStatsPanel'
import TeamStatsPanel from '@/components/TeamStatsPanel'
import { useChatDock } from '@/components/chat/ChatDockProvider'
import { RoleGate, RoleSwitch } from '@/components/role-ui'
import { useUserRole } from '@/components/UserRoleProvider'
import { useFootageLibrary } from '@/hooks/useFootageLibrary'
import { useLiveGameState } from '@/hooks/useLiveGameState'
import type { FootageClip } from '@/lib/footage-library'

function hasLiveStats(clip: FootageClip | null): boolean {
  return clip != null && clip.visionStatus === 'completed' && Boolean(clip.visionResultsKey)
}

function formatQuarter(period?: number): string {
  if (!period || period <= 0) return ''
  if (period > 4) return `OT${period - 4}`
  return `Q${period}`
}

type Props = {
  reviewClip?: FootageClip | null
}

export default function FootageViewTab({ reviewClip = null }: Props) {
  const { role } = useUserRole()
  const isCoach = role === 'coach'
  const { setFloatingHidden } = useChatDock()
  const { clips, loading, error } = useFootageLibrary()

  const mergedClips = useMemo(() => {
    if (!reviewClip) return clips
    const rest = clips.filter((c) => c.id !== reviewClip.id)
    return [reviewClip, ...rest]
  }, [clips, reviewClip])

  const active = reviewClip
    ? mergedClips.find((c) => c.id === reviewClip.id) ?? mergedClips[0] ?? null
    : mergedClips[0] ?? null

  const liveEnabled = hasLiveStats(active)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [videoSecond, setVideoSecond] = useState(0)
  const [trackedClipId, setTrackedClipId] = useState<string | null>(active?.id ?? null)

  // Reset playback tracking when the active clip changes. Setting state during
  // render (instead of in an effect) avoids a cascading render pass.
  if ((active?.id ?? null) !== trackedClipId) {
    setTrackedClipId(active?.id ?? null)
    setVideoSecond(0)
  }

  const { liveState, loading: liveLoading, error: liveError } = useLiveGameState({
    clipId: active?.id,
    enabled: liveEnabled,
    videoSecond,
  })

  useEffect(() => {
    const hideFloating = false // Always show floating chat now
    setFloatingHidden(hideFloating)

    return () => setFloatingHidden(false)
  }, [setFloatingHidden])

  const quarterLabel = formatQuarter(liveState?.period)
  const clockLabel = liveState?.clock ?? '--:--'

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-display text-offwhite text-[clamp(1.6rem,3vw,2.2rem)] tracking-[0.04em] mb-2">
          View Footage
        </h2>
        <p className="text-[0.84rem] text-muted font-light">
          Watch processed game film from your library. Playback is loaded from the viewing pipeline, which is separate from where files are uploaded.
        </p>
      </div>

      <div
        className={
          'grid min-h-[min(60vh,520px)] gap-5 xl:grid-cols-[320px_minmax(0,1fr)_320px]'
        }
      >
        {/* Left Panel - Away Team Stats */}
        <div className="min-h-[min(60vh,520px)]">
          <TeamStatsPanel
            team="away"
            game={active?.game}
            liveTeam={liveEnabled ? liveState?.awayTeam : undefined}
            liveClock={liveEnabled ? liveState?.clock : undefined}
            livePeriod={liveEnabled ? liveState?.period : undefined}
          />
        </div>

        {/* Center - Video */}
        <div className="flex min-h-[min(60vh,520px)] flex-col">
          <div className="flex-1 border border-[rgba(200,136,58,0.15)] rounded-sm bg-black overflow-hidden flex flex-col">
            <div className="aspect-video w-full max-h-[min(56vh,640px)] bg-black flex items-center justify-center relative">
              {loading && (
                <p className="text-[0.8rem] text-muted/60 font-light">Loading…</p>
              )}
              {!loading && error && (
                <p className="text-[0.8rem] text-red-300/80 font-light px-6 text-center">{error}</p>
              )}
              {!loading && !error && active?.playbackUrl ? (
                <video
                  ref={videoRef}
                  key={active.playbackUrl}
                  controls
                  playsInline
                  className="w-full h-full object-contain"
                  src={active.playbackUrl}
                  onTimeUpdate={(event) => {
                    if (!liveEnabled) return
                    setVideoSecond(event.currentTarget.currentTime)
                  }}
                  onSeeked={(event) => {
                    if (!liveEnabled) return
                    setVideoSecond(event.currentTarget.currentTime)
                  }}
                >
                  Your browser does not support video playback.
                </video>
              ) : null}
              {!loading && !error && !active?.playbackUrl && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-8 text-center">
                  <div className="w-12 h-12 rounded-full border border-white/10 flex items-center justify-center">
                    <span className="text-muted/40 text-lg font-light">▶</span>
                  </div>
                  <p className="text-[0.74rem] text-muted/50 font-light max-w-[320px]">
                    <RoleSwitch
                      coach="No plays saved. Even Phil Jackson wrote things down."
                      fan="Nothing here. Emptier than Cleveland's trophy case before 2016."
                      player="No footage yet. LeBron didn't become LeBron by skipping film."
                    />
                  </p>
                </div>
              )}

              {liveEnabled && liveState && (
                <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-sm border border-brand/40 bg-black/70 px-2.5 py-1.5 backdrop-blur-md">
                  <span className="inline-flex items-center gap-1.5 text-[0.55rem] font-semibold uppercase tracking-[0.2em] text-red-300">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
                    Live
                  </span>
                  <span className="font-display text-[0.82rem] tracking-[0.12em] text-offwhite">
                    {quarterLabel || '--'} · {clockLabel}
                  </span>
                </div>
              )}
            </div>
            {active?.playbackUrl && (
              <div className="px-4 py-3 border-t border-[rgba(200,136,58,0.1)]">
                <h3 className="font-display text-offwhite text-lg tracking-wide">{active.title}</h3>
                <p className="text-[0.68rem] text-muted/55 font-light mt-1 tracking-wide uppercase">
                  {liveEnabled
                    ? `Live stats · OCR-aligned · ${quarterLabel || '--'} ${clockLabel}`
                    : 'Playback from your footage library'}
                </p>
                {liveEnabled && liveError && (
                  <p className="mt-2 text-[0.66rem] text-red-300/80 font-light">
                    Live stats unavailable: {liveError}
                  </p>
                )}
                {liveEnabled && liveLoading && !liveError && (
                  <p className="mt-2 text-[0.66rem] text-muted/60 font-light">
                    Loading live stats…
                  </p>
                )}
                {liveEnabled && liveState && liveState.recentEvents.length > 0 && (
                  <div className="mt-3 flex flex-col gap-1">
                    {liveState.recentEvents.slice().reverse().map((evt, i) => (
                      <p
                        key={i}
                        className={`text-[0.64rem] font-light tracking-wide truncate transition-opacity duration-300 ${
                          i === 0 ? 'text-offwhite' : 'text-muted/50'
                        }`}
                      >
                        {evt}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right Panel - Home Team Stats */}
        <div className="min-h-[min(60vh,520px)]">
          <TeamStatsPanel
            team="home"
            game={active?.game}
            liveTeam={liveEnabled ? liveState?.homeTeam : undefined}
            liveClock={liveEnabled ? liveState?.clock : undefined}
            livePeriod={liveEnabled ? liveState?.period : undefined}
          />
        </div>
      </div>
    </div>
  )
}
