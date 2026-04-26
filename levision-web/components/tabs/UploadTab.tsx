'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import type { ESPNTeam } from '@/app/api/teams/search/route'
import type { ParsedGame } from '@/app/api/games/search/route'

// ── Seasons ───────────────────────────────────────────────────────────────────
function buildSeasons() {
  const endYear = new Date().getFullYear()
  return Array.from({ length: 10 }, (_, i) => {
    const year = endYear - i
    return { value: String(year), label: `${year - 1}–${String(year).slice(2)}` }
  })
}
const SEASONS = buildSeasons()

// ── Upload queue types ────────────────────────────────────────────────────────
type UploadStatus = 'queued' | 'uploading' | 'uploaded' | 'processing' | 'ready' | 'invalid' | 'failed'

type UploadItem = {
  id: string
  file: File
  status: UploadStatus
  message?: string
  uploadedUrl?: string
  clipId?: string
  visionStage?: string
}

const STAGE_LABELS: Record<string, string> = {
  downloading:       'Downloading clip...',
  extracting_frames: 'Extracting frames...',
  running_ocr:       'Reading game clock...',
  fetching_pbp:      'Fetching play-by-play...',
  merging:           'Building game timeline...',
  uploading_results: 'Saving results...',
}

const ACCEPTED_FORMATS = '.mp4,.mov,.avi,.mkv,.webm,.m4v'
const ACCEPTED_EXTENSIONS = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v'])

function isVideoFile(file: File) {
  if (file.type.startsWith('video/')) return true
  const ext = file.name.split('.').pop()?.toLowerCase()
  return !!ext && ACCEPTED_EXTENSIONS.has(ext)
}

// ── Shared dropdown list ──────────────────────────────────────────────────────
function DropdownList<T>({
  items,
  getKey,
  renderItem,
  onSelect,
  highlightedIndex,
  itemRefs,
  emptyText,
}: {
  items: T[]
  getKey: (item: T) => string
  renderItem: (item: T) => React.ReactNode
  onSelect: (item: T) => void
  highlightedIndex: number
  itemRefs: React.RefObject<(HTMLButtonElement | null)[]>
  emptyText: string
}) {
  return (
    <div className="absolute top-full left-0 right-0 z-20 mt-1 border border-[rgba(200,136,58,0.18)] bg-[#0d0f12] rounded-sm max-h-52 overflow-y-auto shadow-lg">
      {items.length === 0 ? (
        <div className="px-4 py-3 text-xs text-muted font-body">{emptyText}</div>
      ) : (
        items.map((item, i) => (
          <button
            key={getKey(item)}
            ref={(el) => { if (itemRefs.current) itemRefs.current[i] = el }}
            type="button"
            onMouseDown={(e) => { e.preventDefault(); onSelect(item) }}
            className={`w-full text-left px-4 py-2.5 text-sm font-body transition-colors duration-100 ${
              i === highlightedIndex
                ? 'bg-brand/15 text-offwhite'
                : 'text-offwhite/80 hover:bg-brand/10 hover:text-offwhite'
            }`}
          >
            {renderItem(item)}
          </button>
        ))
      )}
    </div>
  )
}

// ── Season picker ─────────────────────────────────────────────────────────────
function SeasonPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])
  const selected = SEASONS.find((s) => s.value === value) ?? SEASONS[0]

  const close = useCallback(() => { setOpen(false); setHighlightedIndex(-1) }, [])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [close])

  useEffect(() => {
    if (highlightedIndex >= 0) itemRefs.current[highlightedIndex]?.scrollIntoView({ block: 'nearest' })
  }, [highlightedIndex])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(true) } return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlightedIndex((i) => Math.min(i + 1, SEASONS.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlightedIndex((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (highlightedIndex >= 0) { onChange(SEASONS[highlightedIndex].value); close() } }
    else if (e.key === 'Escape') { e.preventDefault(); close() }
  }

  return (
    <div className="flex flex-col gap-1.5" ref={containerRef}>
      <span className="text-brand uppercase text-[0.68rem] tracking-[0.22em] font-medium font-body">Season</span>
      <div className="relative">
        <button
          type="button"
          onClick={() => { setOpen((o) => !o); setHighlightedIndex(SEASONS.findIndex((s) => s.value === value)) }}
          onKeyDown={handleKeyDown}
          className="w-full flex items-center gap-2 border border-brand/30 bg-brand/5 rounded-sm px-3 py-2.5 cursor-pointer"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-brand shrink-0" />
          <span className="font-body text-sm text-offwhite flex-1 text-left">{selected.label}</span>
          <svg
            className={`w-3 h-3 text-muted transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {open && (
          <DropdownList
            items={SEASONS}
            getKey={(s) => s.value}
            renderItem={(s) => <span className="tracking-[0.04em]">{s.label}</span>}
            onSelect={(s) => { onChange(s.value); close() }}
            highlightedIndex={highlightedIndex}
            itemRefs={itemRefs}
            emptyText=""
          />
        )}
      </div>
    </div>
  )
}

// ── Team picker ───────────────────────────────────────────────────────────────
function TeamPicker({
  label, placeholder, allTeams, selected, onSelect, disabled,
}: {
  label: string
  placeholder: string
  allTeams: ESPNTeam[]
  selected: ESPNTeam | null
  onSelect: (team: ESPNTeam | null) => void
  disabled?: boolean
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])

  const filtered = query.trim().length === 0
    ? allTeams.slice(0, 30)
    : allTeams
        .filter((t) =>
          t.displayName.toLowerCase().includes(query.toLowerCase()) ||
          t.abbreviation.toLowerCase().includes(query.toLowerCase()) ||
          t.location.toLowerCase().includes(query.toLowerCase()),
        )
        .slice(0, 8)

  const close = useCallback(() => { setOpen(false); setHighlightedIndex(-1) }, [])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [close])

  useEffect(() => { setHighlightedIndex(-1) }, [query])

  useEffect(() => {
    if (highlightedIndex >= 0) itemRefs.current[highlightedIndex]?.scrollIntoView({ block: 'nearest' })
  }, [highlightedIndex])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlightedIndex((i) => Math.min(i + 1, filtered.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlightedIndex((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      const target = highlightedIndex >= 0 ? filtered[highlightedIndex] : filtered[0]
      if (target) { onSelect(target); setQuery(''); close() }
    }
    else if (e.key === 'Escape') { e.preventDefault(); close() }
  }

  return (
    <div className="flex flex-col gap-1.5" ref={containerRef}>
      <span className="text-brand uppercase text-[0.68rem] tracking-[0.22em] font-medium font-body">{label}</span>
      {selected ? (
        <div className="flex items-center gap-2 border border-brand/30 bg-brand/5 rounded-sm px-3 py-2.5">
          <span className="w-1.5 h-1.5 rounded-full bg-brand shrink-0" />
          <span className="font-body text-sm text-offwhite flex-1 truncate">{selected.displayName}</span>
          <button
            type="button"
            onMouseDown={(e) => { e.preventDefault(); onSelect(null); setQuery('') }}
            className="text-muted hover:text-offwhite transition-colors duration-200 text-[0.6rem] tracking-widest"
          >
            ✕
          </button>
        </div>
      ) : (
        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setOpen(true)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            className="w-full bg-white/[0.04] border border-white/10 focus:border-brand focus:bg-brand/5 rounded-sm px-4 py-2.5 text-offwhite font-body font-light text-sm outline-none transition-colors duration-200 placeholder:text-white/20 disabled:opacity-40 disabled:cursor-not-allowed"
          />
          {open && allTeams.length > 0 && (
            <DropdownList
              items={filtered}
              getKey={(t) => t.id}
              renderItem={(t) => (
                <span className="flex items-center gap-3">
                  <span className="text-muted text-xs w-8 shrink-0">{t.abbreviation}</span>
                  {t.displayName}
                </span>
              )}
              onSelect={(t) => { onSelect(t); setQuery(''); close() }}
              highlightedIndex={highlightedIndex}
              itemRefs={itemRefs}
              emptyText="No teams match"
            />
          )}
        </div>
      )}
    </div>
  )
}

// ── Skeleton loader ───────────────────────────────────────────────────────────
function GamesSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 mt-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="rounded-sm border border-[rgba(200,136,58,0.08)] bg-[rgba(200,136,58,0.02)] px-3 py-2.5 animate-pulse"
        >
          <div className="h-4 w-20 bg-white/[0.06] rounded-sm mb-2" />
          <div className="h-3 w-28 bg-white/[0.04] rounded-sm" />
        </div>
      ))}
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ item }: { item: UploadItem }) {
  const isProcessing = item.status === 'processing'
  const stageLabel = isProcessing && item.visionStage ? STAGE_LABELS[item.visionStage] ?? item.visionStage : null

  const color =
    item.status === 'invalid' || item.status === 'failed' ? 'text-accent/80'
    : item.status === 'ready' ? 'text-brand/80'
    : item.status === 'processing' ? 'text-brand/60 animate-pulse'
    : item.status === 'uploaded' ? 'text-muted'
    : item.status === 'uploading' ? 'text-muted animate-pulse'
    : 'text-muted'

  return (
    <div>
      <p className={`text-[0.7rem] mt-0.5 font-body ${color}`}>{item.message}</p>
      {stageLabel && (
        <p className="text-[0.65rem] mt-0.5 font-body text-brand/40">{stageLabel}</p>
      )}
    </div>
  )
}

// ── SSE event shape ───────────────────────────────────────────────────────────
type VisionUpdateEvent = {
  type: 'vision_update'
  clip_id: string
  event: 'stage_update' | 'completed' | 'failed'
  stage: string | null
  results_key: string | null
  error: string | null
}

// ── Main component ────────────────────────────────────────────────────────────
export default function UploadTab() {
  // Game context
  const [season, setSeason] = useState(SEASONS[0].value)
  const [allTeams, setAllTeams] = useState<ESPNTeam[]>([])
  const [teamsLoading, setTeamsLoading] = useState(false)
  const [team1, setTeam1] = useState<ESPNTeam | null>(null)
  const [team2, setTeam2] = useState<ESPNTeam | null>(null)

  // Games search
  const [games, setGames] = useState<ParsedGame[]>([])
  const [gamesLoading, setGamesLoading] = useState(false)
  const [gamesError, setGamesError] = useState<string | null>(null)
  const [selectedGame, setSelectedGame] = useState<ParsedGame | null>(null)

  // Upload queue
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Load all teams once on mount
  useEffect(() => {
    setTeamsLoading(true)
    fetch('/api/teams/search?all=true')
      .then((r) => r.json())
      .then((data: { teams?: ESPNTeam[] }) => setAllTeams(data.teams ?? []))
      .catch(() => {})
      .finally(() => setTeamsLoading(false))
  }, [])

  // SSE: subscribe to processing updates
  useEffect(() => {
    const es = new EventSource('/api/events')

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as { type?: string }
        if (data.type !== 'vision_update') return
        const update = data as VisionUpdateEvent

        setUploads((prev) =>
          prev.map((item) => {
            if (item.clipId !== update.clip_id) return item
            if (update.event === 'stage_update') {
              return { ...item, visionStage: update.stage ?? undefined }
            }
            if (update.event === 'completed') {
              return { ...item, status: 'ready', message: 'Analysis complete.', visionStage: undefined }
            }
            if (update.event === 'failed') {
              return { ...item, status: 'failed', message: update.error ?? 'Analysis failed.', visionStage: undefined }
            }
            return item
          })
        )
      } catch { /* malformed event */ }
    }

    return () => es.close()
  }, [])

  // Debounced game fetch
  useEffect(() => {
    if (!season || !team1) {
      setGames([])
      setGamesError(null)
      setGamesLoading(false)
      return
    }

    setGamesLoading(true)
    setGamesError(null)

    const controller = new AbortController()
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ season, team_one_id: team1.id })
      if (team2) params.set('team_two_id', team2.id)

      fetch(`/api/games/search?${params.toString()}`, { signal: controller.signal })
        .then((r) => r.json())
        .then((data: { games?: ParsedGame[]; error?: string }) => {
          if (data.error) throw new Error(data.error)
          setGames(data.games ?? [])
          setSelectedGame(null)
        })
        .catch((err: unknown) => {
          if (err instanceof Error && err.name === 'AbortError') return
          setGamesError('Failed to load games')
          setGames([])
        })
        .finally(() => setGamesLoading(false))
    }, 350)

    return () => { clearTimeout(timer); controller.abort() }
  }, [season, team1?.id, team2?.id])

  useEffect(() => { if (!team1) setTeam2(null) }, [team1])

  // ── Upload handlers ─────────────────────────────────────────────────────────
  const queueFiles = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    const next: UploadItem[] = Array.from(fileList).map((file) => {
      const valid = isVideoFile(file)
      return {
        id: `${file.name}-${file.size}-${file.lastModified}`,
        file,
        status: valid ? 'queued' : 'invalid',
        message: valid ? 'Queued for ingest' : 'Only video files are allowed',
      }
    })
    setUploads((prev) => [...next, ...prev])
  }

  const removeUpload = (id: string) => setUploads((prev) => prev.filter((item) => item.id !== id))

  const confirmUpload = async () => {
    const queued = uploads.filter((item) => item.status === 'queued')
    if (queued.length === 0 || !selectedGame) return

    setIsUploading(true)
    setUploads((prev) =>
      prev.map((item) =>
        item.status === 'queued' ? { ...item, status: 'uploading', message: 'Uploading...' } : item,
      ),
    )

    const results = await Promise.all(
      queued.map(async (item) => {
        const formData = new FormData()
        formData.append('file', item.file)
        try {
          // Step 1: upload file to R2 + create footage row
          const uploadRes = await fetch('/api/upload', { method: 'POST', body: formData })
          const uploadPayload = (await uploadRes.json()) as { key?: string; url?: string; clipId?: string; error?: string }
          if (!uploadRes.ok) {
            return { id: item.id, status: 'failed' as UploadStatus, message: uploadPayload.error ?? 'Upload failed. Blame the refs.' }
          }

          const clipId = uploadPayload.clipId!

          // Step 2: link to game — this triggers the Modal pipeline
          const linkRes = await fetch(`/api/footage/${clipId}/link-game`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              espn_game_id: selectedGame.espn_game_id,
              home_team_id: selectedGame.home_team_id,
              away_team_id: selectedGame.away_team_id,
              game_date: selectedGame.date,
              game_season: season,
            }),
          })

          if (!linkRes.ok) {
            return {
              id: item.id,
              status: 'uploaded' as UploadStatus,
              message: 'Uploaded but failed to link game.',
              uploadedUrl: uploadPayload.url ?? undefined,
              clipId,
            }
          }

          return {
            id: item.id,
            status: 'processing' as UploadStatus,
            message: 'Footage locked in. Analyzing...',
            uploadedUrl: uploadPayload.url ?? undefined,
            clipId,
            visionStage: 'downloading',
          }
        } catch {
          return { id: item.id, status: 'failed' as UploadStatus, message: 'Upload failed. Blame the refs.' }
        }
      }),
    )

    const byId = new Map(results.map((r) => [r.id, r]))
    setUploads((prev) => prev.map((item) => { const r = byId.get(item.id); return r ? { ...item, ...r } : item }))
    setIsUploading(false)
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col">
      <h2 className="font-display text-offwhite text-[clamp(1.6rem,3vw,2.2rem)] tracking-[0.04em] mb-2">
        Upload Footage
      </h2>
      <p className="text-[0.84rem] text-muted font-light mb-8">
        Drop your footage. We&apos;ll get it ready for the film room.
      </p>

      {/* ── Step 1: Game search ── */}
      <div className="border border-[rgba(200,136,58,0.12)] rounded-sm bg-[rgba(200,136,58,0.015)] p-5 mb-6">
        <div className="flex items-center gap-3 mb-4">
          <span className="flex items-center justify-center w-5 h-5 rounded-full border border-brand/50 text-brand text-[0.62rem] font-display tracking-wider shrink-0">1</span>
          <p className="text-brand uppercase text-[0.68rem] tracking-[0.22em] font-medium font-body">
            Game Search
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
          <SeasonPicker value={season} onChange={setSeason} />
          <TeamPicker
            label="Team 1"
            placeholder={teamsLoading ? 'Loading...' : 'Search teams…'}
            allTeams={allTeams}
            selected={team1}
            onSelect={(t) => { setTeam1(t); if (!t) setTeam2(null) }}
            disabled={teamsLoading}
          />
          <TeamPicker
            label="Team 2"
            placeholder={team1 ? 'Narrow to head-to-head…' : 'Select Team 1 first'}
            allTeams={allTeams.filter((t) => t.id !== team1?.id)}
            selected={team2}
            onSelect={setTeam2}
            disabled={!team1}
          />
        </div>

        {!team1 && (
          <p className="text-[0.74rem] text-muted/60 font-light">
            Select a season and team to load completed games.
          </p>
        )}
        {team1 && gamesLoading && <GamesSkeleton />}
        {team1 && !gamesLoading && gamesError && (
          <p className="text-[0.74rem] text-accent font-light mt-3">{gamesError}</p>
        )}
        {team1 && !gamesLoading && !gamesError && games.length === 0 && (
          <p className="text-[0.74rem] text-muted/60 font-light mt-3">
            No completed games found for this selection.
          </p>
        )}
        {!gamesLoading && games.length > 0 && (
          <div>
            <p className="text-[0.7rem] text-muted/70 font-light mb-3">
              {selectedGame
                ? `Linked: ${selectedGame.label} · ${new Date(selectedGame.date).toLocaleDateString()}`
                : 'Select a game to link uploaded footage'}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-64 overflow-y-auto pr-1">
              {games.map((g) => {
                const isSelected = selectedGame?.espn_game_id === g.espn_game_id
                return (
                  <button
                    key={g.espn_game_id}
                    type="button"
                    onClick={() => setSelectedGame(isSelected ? null : g)}
                    className={`text-left rounded-sm px-3 py-2.5 border transition-colors duration-150 cursor-pointer ${
                      isSelected
                        ? 'border-brand bg-brand/10'
                        : 'border-[rgba(200,136,58,0.12)] bg-transparent hover:bg-[rgba(200,136,58,0.04)] hover:border-[rgba(200,136,58,0.25)]'
                    }`}
                  >
                    <div className={`font-display text-base tracking-[0.04em] ${isSelected ? 'text-brand' : 'text-offwhite'}`}>
                      {g.away_abbrev} @ {g.home_abbrev}
                    </div>
                    <div className="font-body text-[0.7rem] mt-0.5 text-muted">
                      {new Date(g.date).toLocaleDateString()}
                      {g.away_score && g.home_score && (
                        <span className="ml-2 text-offwhite/50">{g.away_score}–{g.home_score}</span>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* ── Step 2: Drop zone ── */}
      <div className={`transition-opacity duration-300 ${selectedGame ? 'opacity-100' : 'opacity-40 pointer-events-none select-none'}`}>
        <div className="flex items-center gap-3 mb-4">
          <span className={`flex items-center justify-center w-5 h-5 rounded-full border text-[0.62rem] font-display tracking-wider shrink-0 transition-colors duration-300 ${selectedGame ? 'border-brand/50 text-brand' : 'border-white/20 text-muted'}`}>2</span>
          <p className={`uppercase text-[0.68rem] tracking-[0.22em] font-medium font-body transition-colors duration-300 ${selectedGame ? 'text-brand' : 'text-muted'}`}>
            Drop Footage
          </p>
        </div>
        <button
          type="button"
          onClick={() => selectedGame && fileInputRef.current?.click()}
          onDragOver={(e) => { if (!selectedGame) return; e.preventDefault(); setIsDragging(true) }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => { e.preventDefault(); setIsDragging(false); if (selectedGame) queueFiles(e.dataTransfer.files) }}
          className={`w-full border border-dashed rounded-sm p-12 text-center transition-colors duration-200 mb-5 cursor-pointer ${
            isDragging
              ? 'border-brand bg-[rgba(200,136,58,0.05)]'
              : 'border-[rgba(200,136,58,0.28)] bg-[rgba(200,136,58,0.02)] hover:border-brand hover:bg-[rgba(200,136,58,0.05)]'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_FORMATS}
            multiple
            className="hidden"
            onChange={(e) => { queueFiles(e.target.files); e.target.value = '' }}
          />
          <div className="font-display text-[1.3rem] tracking-[0.08em] text-offwhite mb-2">
            Drop footage here or click to browse
          </div>
          <div className="text-[0.76rem] text-muted font-light mb-4">
            Game film, practice sessions, highlight cuts
          </div>
          {selectedGame && (
            <div className="inline-flex items-center gap-2 border border-brand/30 bg-brand/5 rounded-sm px-3 py-1.5 mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-brand shrink-0" />
              <span className="text-[0.72rem] font-body text-offwhite">
                Will link to {selectedGame.label}
              </span>
            </div>
          )}
          <div className="flex gap-2 justify-center">
            {['MP4', 'MOV', 'AVI', 'MKV'].map((fmt) => (
              <span key={fmt} className="text-[0.62rem] tracking-[0.12em] px-2.5 py-1 border border-[rgba(200,136,58,0.18)] rounded-sm text-muted">
                {fmt}
              </span>
            ))}
          </div>
        </button>

        {/* ── Upload queue ── */}
        {uploads.length > 0 && (
          <div className="border border-[rgba(200,136,58,0.12)] rounded-sm bg-[rgba(200,136,58,0.015)]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[rgba(200,136,58,0.12)]">
              <p className="text-[0.74rem] tracking-[0.12em] uppercase text-muted">Selected files</p>
              <button
                type="button"
                onClick={confirmUpload}
                disabled={isUploading || !uploads.some((item) => item.status === 'queued')}
                className="text-[0.68rem] tracking-[0.12em] uppercase px-3 py-1.5 rounded-sm border border-brand/40 text-offwhite bg-brand/10 hover:bg-brand/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors duration-200"
              >
                {isUploading ? 'Uploading...' : 'Upload queued files'}
              </button>
            </div>
            <div className="divide-y divide-[rgba(200,136,58,0.08)]">
              {uploads.map((item) => (
                <div key={item.id} className="px-4 py-3 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm text-offwhite truncate font-body">{item.file.name}</p>
                    {selectedGame && item.status === 'queued' && (
                      <p className="text-[0.68rem] text-brand/70 mt-0.5 font-body">{selectedGame.label}</p>
                    )}
                    <StatusBadge item={item} />
                    {item.uploadedUrl && (
                      <a href={item.uploadedUrl} target="_blank" rel="noreferrer" className="inline-block mt-1 text-[0.68rem] text-brand hover:text-brand/80 transition-colors duration-200">
                        Open uploaded file
                      </a>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => removeUpload(item.id)}
                    className="text-[0.64rem] tracking-[0.1em] uppercase text-muted hover:text-offwhite transition-colors duration-200 shrink-0 mt-0.5"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {uploads.length === 0 && (
          <p className="text-[0.74rem] text-muted/50 font-light">
            No footage yet. LeBron didn&apos;t become LeBron by skipping film.
          </p>
        )}
      </div>
    </div>
  )
}
