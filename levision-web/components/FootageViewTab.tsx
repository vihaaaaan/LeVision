'use client'

import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import { RoleSwitch } from '@/components/role-ui'
import { useClipPlayerMontage } from '@/hooks/useClipPlayerMontage'
import { useFootageLibrary } from '@/hooks/useFootageLibrary'
import type { FootageClip, PlayerAppearanceSegment } from '@/lib/footage-library'

const PAST_GAME_ID_PREFIX = 'past-game-'
const MONTAGE_END_BUFFER_SECONDS = 0.2

function isPastGameClip(clip: FootageClip | null): boolean {
  return clip != null && clip.id.startsWith(PAST_GAME_ID_PREFIX)
}

function formatTimestamp(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const remainingSeconds = totalSeconds % 60

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
  }

  return `${minutes}:${String(remainingSeconds).padStart(2, '0')}`
}

type Props = {
  reviewClip?: FootageClip | null
}

export default function FootageViewTab({ reviewClip = null }: Props) {
  const { clips, loading, error } = useFootageLibrary()
  const [playerSelection, setPlayerSelection] = useState<{
    clipId: string | null
    playerName: string | null
  }>({
    clipId: null,
    playerName: null,
  })
  const [montageIndex, setMontageIndex] = useState(0)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const transitionTimeoutRef = useRef<number | null>(null)
  const montageSegmentsRef = useRef<PlayerAppearanceSegment[]>([])
  const montageIndexRef = useRef(0)
  const isTransitioningRef = useRef(false)

  const mergedClips = useMemo(() => {
    if (!reviewClip) return clips
    const rest = clips.filter((c) => c.id !== reviewClip.id)
    return [reviewClip, ...rest]
  }, [clips, reviewClip])

  const activeId = reviewClip?.id ?? null
  const active = mergedClips.find((c) => c.id === activeId) ?? null
  const { montage, loading: montageLoading, error: montageError } = useClipPlayerMontage(active?.id ?? null)
  const selectedPlayer = useMemo(() => {
    if (!montage || montage.players.length === 0) return null

    if (
      playerSelection.clipId === active?.id &&
      playerSelection.playerName &&
      montage.segmentsByPlayer[playerSelection.playerName]
    ) {
      return playerSelection.playerName
    }

    return montage.players[0]?.name ?? null
  }, [active?.id, montage, playerSelection])

  const activePlayerSegments = useMemo(() => {
    if (!selectedPlayer || !montage) return []
    return montage.segmentsByPlayer[selectedPlayer] ?? []
  }, [montage, selectedPlayer])

  useEffect(() => {
    montageSegmentsRef.current = []
    montageIndexRef.current = 0
  }, [active?.id])

  useEffect(() => {
    montageSegmentsRef.current = activePlayerSegments
    montageIndexRef.current = montageIndex
  }, [activePlayerSegments, montageIndex])

  useEffect(() => {
    return () => {
      if (transitionTimeoutRef.current != null) {
        window.clearTimeout(transitionTimeoutRef.current)
      }
    }
  }, [])

  const playSegmentAtIndex = useEffectEvent(async (nextIndex: number) => {
    const video = videoRef.current
    const nextSegment = montageSegmentsRef.current[nextIndex]
    if (!video || !nextSegment) return

    if (transitionTimeoutRef.current != null) {
      window.clearTimeout(transitionTimeoutRef.current)
    }

    isTransitioningRef.current = true
    montageIndexRef.current = nextIndex
    setMontageIndex(nextIndex)

    video.currentTime = nextSegment.start

    try {
      await video.play()
    } catch {
      // Autoplay may be blocked until the user interacts with the video controls.
    }

    transitionTimeoutRef.current = window.setTimeout(() => {
      isTransitioningRef.current = false
    }, 150)
  })

  useEffect(() => {
    if (activePlayerSegments.length === 0) return

    void playSegmentAtIndex(0)
  }, [activePlayerSegments.length, selectedPlayer])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const handleTimeUpdate = () => {
      const currentSegments = montageSegmentsRef.current
      const currentSegment = currentSegments[montageIndexRef.current]
      if (!currentSegment || isTransitioningRef.current) return

      if (video.currentTime < currentSegment.end - MONTAGE_END_BUFFER_SECONDS) return

      const nextIndex = montageIndexRef.current + 1
      if (nextIndex >= currentSegments.length) {
        video.pause()
        return
      }

      void playSegmentAtIndex(nextIndex)
    }

    video.addEventListener('timeupdate', handleTimeUpdate)
    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate)
    }
  }, [active?.playbackUrl])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="font-display text-offwhite text-[clamp(1.6rem,3vw,2.2rem)] tracking-[0.04em] mb-2">
          View Footage
        </h2>
        <p className="text-[0.84rem] text-muted font-light max-w-[52ch]">
          Watch processed game film from your library. Playback is loaded from the viewing
          pipeline, which is separate from where files are uploaded.
        </p>
      </div>

      <div className="min-h-[min(60vh,520px)] flex flex-col">
        <div className="flex-1 border border-[rgba(200,136,58,0.15)] rounded-sm bg-black overflow-hidden flex flex-col lg:flex-row">
          <aside className="w-full lg:w-[280px] xl:w-[320px] border-b lg:border-b-0 lg:border-r border-[rgba(200,136,58,0.12)] bg-[linear-gradient(180deg,rgba(200,136,58,0.08),rgba(200,136,58,0.02))]">
            <div className="px-4 py-4 border-b border-[rgba(200,136,58,0.12)]">
              <p className="text-[0.68rem] tracking-[0.18em] uppercase text-brand-light/80">
                Player Montage
              </p>
              <h3 className="font-display text-offwhite text-[1.25rem] tracking-[0.05em] mt-2">
                Jump to every shift
              </h3>
              <p className="text-[0.74rem] text-muted font-light mt-2 max-w-[30ch]">
                Select a player and the film will jump through each timestamp where they appear.
              </p>
            </div>

            <div className="max-h-[320px] lg:max-h-none lg:h-full overflow-y-auto chat-scroll px-3 py-3 space-y-2">
              {loading && (
                <p className="text-[0.8rem] text-muted/60 font-light px-2 py-2">Loading footage…</p>
              )}
              {!loading && error && (
                <p className="text-[0.8rem] text-red-300/80 font-light px-2 py-2">{error}</p>
              )}
              {!loading && !error && !active?.playbackUrl && (
                <p className="text-[0.8rem] text-muted/60 font-light px-2 py-2">
                  Open a game in Past Games to build a player montage from its timeline rows.
                </p>
              )}
              {!loading && !error && active?.playbackUrl && montageLoading && (
                <p className="text-[0.8rem] text-muted/60 font-light px-2 py-2">
                  Loading player timestamps…
                </p>
              )}
              {!loading && !error && active?.playbackUrl && !montageLoading && montageError && (
                <p className="text-[0.8rem] text-red-300/80 font-light px-2 py-2">{montageError}</p>
              )}
              {!loading &&
                !error &&
                active?.playbackUrl &&
                !montageLoading &&
                !montageError &&
                montage?.players.length === 0 && (
                  <p className="text-[0.8rem] text-muted/60 font-light px-2 py-2">
                    No player timestamps were found for this clip yet.
                  </p>
                )}
              {montage?.players.map((player) => {
                const isActive = player.name === selectedPlayer
                return (
                  <button
                    key={player.name}
                    type="button"
                    onClick={() => setPlayerSelection({ clipId: active?.id ?? null, playerName: player.name })}
                    className={`w-full text-left rounded-sm border px-3 py-3 transition-colors duration-200 ${
                      isActive
                        ? 'border-brand bg-[rgba(200,136,58,0.16)]'
                        : 'border-[rgba(200,136,58,0.14)] bg-[rgba(255,255,255,0.02)] hover:border-brand/50 hover:bg-[rgba(200,136,58,0.08)]'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm text-offwhite truncate">{player.name}</p>
                        <p className="text-[0.65rem] tracking-[0.14em] uppercase text-muted mt-1">
                          First seen {formatTimestamp(player.firstAppearance)}
                        </p>
                      </div>
                      <span className="text-[0.68rem] text-brand-light whitespace-nowrap">
                        {player.segmentCount} cuts
                      </span>
                    </div>
                    <p className="text-[0.72rem] text-muted/80 font-light mt-3">
                      {formatTimestamp(player.totalDuration)} total montage time
                    </p>
                  </button>
                )
              })}
            </div>
          </aside>

          <div className="flex-1 flex flex-col">
            <div className="aspect-video w-full max-h-[min(56vh,640px)] bg-black flex items-center justify-center relative">
              {loading && (
                <p className="text-[0.8rem] text-muted/60 font-light">Loading…</p>
              )}
              {!loading && error && (
                <p className="text-[0.8rem] text-red-300/80 font-light px-6 text-center">{error}</p>
              )}
              {!loading && !error && active?.playbackUrl ? (
                <video
                  key={active.playbackUrl}
                  ref={videoRef}
                  controls
                  playsInline
                  className="w-full h-full object-contain"
                  src={active.playbackUrl}
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
            </div>
            {active?.playbackUrl && (
              <div className="px-4 py-3 border-t border-[rgba(200,136,58,0.1)]">
                <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                  <div>
                    <h3 className="font-display text-offwhite text-lg tracking-wide">{active.title}</h3>
                    <p className="text-[0.68rem] text-muted/55 font-light mt-1 tracking-wide uppercase">
                      {isPastGameClip(active)
                        ? 'Opened from Past Games'
                        : 'Playback source: library pipeline (not upload ingest)'}
                    </p>
                  </div>
                  {selectedPlayer && activePlayerSegments.length > 0 && (
                    <div className="text-[0.72rem] text-muted/75 font-light">
                      {selectedPlayer}: clip {montageIndex + 1} of {activePlayerSegments.length}
                      {' · '}
                      {formatTimestamp(activePlayerSegments[montageIndex]?.start ?? 0)}
                      {' - '}
                      {formatTimestamp(activePlayerSegments[montageIndex]?.end ?? 0)}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
