import { useEffect, useMemo, useRef, useState } from 'react'
import TeamStatsPanel from '@/components/TeamStatsPanel'
import { useChatDock } from '@/components/chat/ChatDockProvider'
import { RoleSwitch } from '@/components/role-ui'
import { useUserRole } from '@/components/UserRoleProvider'
import { useFootageLibrary } from '@/hooks/useFootageLibrary'
import { useLiveGameState } from '@/hooks/useLiveGameState'
import type { FootageClip } from '@/lib/footage-library'
import type { LivePlay } from '@/lib/types'

const PAST_GAME_ID_PREFIX = 'past-game-'
const LAKERS_WARRIORS_CHRISTMAS_PATTERN = /lakers[\s_-]*warriors[\s_-]*christmas/i

function isPastGameClip(clip: FootageClip | null): boolean {
  return clip != null && clip.id.startsWith(PAST_GAME_ID_PREFIX)
}

function isLakersWarriorsChristmasClip(clip: FootageClip | null): boolean {
  if (!clip) return false
  const haystack = `${clip.title ?? ''} ${clip.playbackUrl ?? ''} ${clip.id ?? ''}`
  return LAKERS_WARRIORS_CHRISTMAS_PATTERN.test(haystack)
}

function formatQuarter(period?: number): string {
  if (!period || period <= 0) return ''
  if (period > 4) return `OT${period - 4}`
  return `Q${period}`
}

function clockToRemainingSeconds(clock: string | null | undefined): number | null {
  if (!clock) return null
  const [minutesText, secondsText] = clock.split(':')
  const minutes = Number(minutesText)
  const seconds = Number(secondsText)
  if (!Number.isFinite(minutes) || !Number.isFinite(seconds)) return null
  return minutes * 60 + seconds
}

function elapsedSecondsForPeriod(period: number, clock: string): number | null {
  const remaining = clockToRemainingSeconds(clock)
  if (remaining == null) return null
  const periodLength = period > 4 ? 5 * 60 : 12 * 60
  return periodLength - remaining
}

function findActivePlay(
  plays: LivePlay[],
  period: number | undefined,
  clock: string | undefined,
): LivePlay | null {
  if (!period || !clock) return null
  const currentElapsed = elapsedSecondsForPeriod(period, clock)
  if (currentElapsed == null) return null

  let candidate: LivePlay | null = null
  let candidateElapsed = -1

  for (const play of plays) {
    if (play.period !== period) continue
    const playElapsed = elapsedSecondsForPeriod(play.period, play.clock)
    if (playElapsed == null) continue
    if (playElapsed <= currentElapsed && playElapsed >= candidateElapsed) {
      candidate = play
      candidateElapsed = playElapsed
    }
  }

  return candidate
}

function findVideoSecondForPlay(
  timeline: ReturnType<typeof useLiveGameState>['timeline'],
  play: LivePlay,
): number | null {
  if (!timeline) return null

  let exactMatch: number | null = null
  let nearestSecond: number | null = null
  let nearestDelta = Number.POSITIVE_INFINITY
  const targetRemaining = clockToRemainingSeconds(play.clock)

  for (const [snapshotKey, snapshot] of Object.entries(timeline.snapshots)) {
    if (snapshot.period !== play.period) continue

    const videoSecond = Number(snapshotKey) - 1
    if (!Number.isFinite(videoSecond)) continue

    if (snapshot.clock === play.clock) {
      if (exactMatch == null || videoSecond < exactMatch) {
        exactMatch = videoSecond
      }
      continue
    }

    const snapshotRemaining = clockToRemainingSeconds(snapshot.clock)
    if (targetRemaining == null || snapshotRemaining == null) continue

    const delta = Math.abs(snapshotRemaining - targetRemaining)
    if (delta < nearestDelta) {
      nearestDelta = delta
      nearestSecond = videoSecond
    }
  }

  return exactMatch ?? nearestSecond
}

type Props = {
  reviewClip?: FootageClip | null
}

export default function FootageViewTab({ reviewClip = null }: Props) {
  const { role } = useUserRole()
  const isFan = role === 'fan'
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

  const isChristmasClip = isLakersWarriorsChristmasClip(active)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [videoSecond, setVideoSecond] = useState(0)
  const [trackedClipId, setTrackedClipId] = useState<string | null>(active?.id ?? null)

  // Reset playback tracking when the active clip changes. Setting state during
  // render (instead of in an effect) avoids a cascading render pass.
  if ((active?.id ?? null) !== trackedClipId) {
    setTrackedClipId(active?.id ?? null)
    setVideoSecond(0)
  }

  const { liveState, timeline, loading: liveLoading, error: liveError } = useLiveGameState({
    enabled: isChristmasClip,
    videoSecond,
  })

  useEffect(() => {
    const hideFloating = false // Always show floating chat now
    setFloatingHidden(hideFloating)

    return () => setFloatingHidden(false)
  }, [setFloatingHidden])

  const quarterLabel = formatQuarter(liveState?.period)
  const clockLabel = liveState?.clock ?? '--:--'
  const fanPlays = timeline?.plays ?? []
  const activePlay = useMemo(
    () => findActivePlay(fanPlays, liveState?.period, liveState?.clock),
    [fanPlays, liveState?.period, liveState?.clock],
  )

  const handlePlayClick = (play: LivePlay) => {
    const targetSecond = findVideoSecondForPlay(timeline, play)
    const video = videoRef.current
    if (!video || targetSecond == null) return

    const leadInSecond = Math.max(0, targetSecond - 3)
    video.currentTime = leadInSecond
    setVideoSecond(leadInSecond)
  }

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
          isFan
            ? 'grid min-h-[min(60vh,520px)] gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]'
            : 'grid min-h-[min(60vh,520px)] gap-5 xl:grid-cols-[320px_minmax(0,1fr)_320px]'
        }
      >
        {!isFan && (
          <div className="min-h-[min(60vh,520px)]">
            <TeamStatsPanel
              team="away"
              game={active?.game}
              liveTeam={isChristmasClip ? liveState?.awayTeam : undefined}
              liveClock={isChristmasClip ? liveState?.clock : undefined}
              livePeriod={isChristmasClip ? liveState?.period : undefined}
            />
          </div>
        )}

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
                    if (!isChristmasClip) return
                    setVideoSecond(event.currentTarget.currentTime)
                  }}
                  onSeeked={(event) => {
                    if (!isChristmasClip) return
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

              {isChristmasClip && liveState && (
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
                  {isChristmasClip
                    ? `Live stats · OCR-aligned · ${quarterLabel || '--'} ${clockLabel}`
                    : isPastGameClip(active)
                      ? 'Opened from Past Games'
                      : 'Playback source: library pipeline (not upload ingest)'}
                </p>
                {isChristmasClip && liveError && (
                  <p className="mt-2 text-[0.66rem] text-red-300/80 font-light">
                    Live stats unavailable: {liveError}
                  </p>
                )}
                {isChristmasClip && liveLoading && !liveError && (
                  <p className="mt-2 text-[0.66rem] text-muted/60 font-light">
                    Loading live stats…
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {isFan ? (
          <div className="min-h-[min(60vh,520px)] border border-[rgba(200,136,58,0.15)] rounded-sm bg-[rgba(9,11,14,0.9)] overflow-hidden">
            <div className="px-4 py-3 border-b border-[rgba(200,136,58,0.1)]">
              <h3 className="font-display text-offwhite text-lg tracking-wide">Play-by-Play</h3>
              <p className="text-[0.68rem] text-muted/55 font-light mt-1 tracking-wide uppercase">
                Synced to the current game state
              </p>
            </div>
            <div className="max-h-[min(60vh,520px)] overflow-y-auto">
              {fanPlays.length > 0 ? (
                fanPlays.map((play) => {
                  const isActivePlay = activePlay?.id === play.id
                  return (
                    <button
                      key={play.id}
                      type="button"
                      onClick={() => handlePlayClick(play)}
                      className={`w-full text-left px-4 py-3 border-b border-[rgba(200,136,58,0.08)] transition-colors duration-150 cursor-pointer ${
                        isActivePlay ? 'bg-brand/10' : 'hover:bg-white/[0.03]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-[0.62rem] tracking-[0.14em] uppercase text-brand/80">
                          {formatQuarter(play.period)} · {play.clock}
                          {play.teamAbbrev ? ` · ${play.teamAbbrev}` : ''}
                        </div>
                        {play.videoAvailable && (
                          <span className="text-[0.58rem] tracking-[0.14em] uppercase text-brand/70">
                            Video
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-[0.78rem] text-offwhite/90 leading-5">
                        {play.description}
                      </p>
                      {(play.scoreAway || play.scoreHome) && (
                        <p className="mt-1 text-[0.66rem] text-muted/60">
                          Score: {play.scoreAway ?? '--'} - {play.scoreHome ?? '--'}
                        </p>
                      )}
                    </button>
                  )
                })
              ) : (
                <p className="px-4 py-4 text-[0.72rem] text-muted/60 font-light">
                  Play-by-play unavailable.
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="min-h-[min(60vh,520px)]">
            <TeamStatsPanel
              team="home"
              game={active?.game}
              liveTeam={isChristmasClip ? liveState?.homeTeam : undefined}
              liveClock={isChristmasClip ? liveState?.clock : undefined}
              livePeriod={isChristmasClip ? liveState?.period : undefined}
            />
          </div>
        )}
      </div>
    </div>
  )
}
