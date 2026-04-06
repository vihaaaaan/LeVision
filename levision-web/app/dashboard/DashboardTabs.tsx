'use client'

import { useEffect, useRef, useState } from 'react'
import type { Game } from '@/lib/types'
import type { FootageClip } from '@/lib/footage-library'
import { RoleSwitch } from '@/components/role-ui'
import FootageViewTab from '@/components/FootageViewTab'

function gameToReviewClip(game: Game): FootageClip {
  return {
    id: `past-game-${game.id}`,
    title: `${game.awayTeam} @ ${game.homeTeam}`,
    createdAt: game.date,
    playbackUrl: game.videoUrl ?? null,
  }
}

type Tab = 'view' | 'upload' | 'past'
type UploadStatus = 'queued' | 'uploading' | 'uploaded' | 'invalid' | 'failed'

type UploadItem = {
  id: string
  file: File
  status: UploadStatus
  message?: string
  uploadedUrl?: string
}

type UploadedVideo = {
  key: string
  name: string
  size: number
  lastModified: string | null
  url: string
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'upload', label: 'Upload Footage' },
  { id: 'past',   label: 'Past Games' },
  { id: 'view',   label: 'View Footage' },
]

// Mock past games data
const MOCK_GAMES: Game[] = [
  {
    id: '1',
    homeTeam: 'Lakers',
    awayTeam: 'Warriors',
    homeScore: 115,
    awayScore: 110,
    date: '2024-03-01',
    videoUrl:
      'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4',
    stats: {
      homePoints: 115,
      awayPoints: 110,
      homeRebounds: 45,
      awayRebounds: 38,
      homeAssists: 28,
      awayAssists: 25,
      homeSteals: 8,
      awaySteals: 6,
      homeBlocks: 5,
      awayBlocks: 3,
      homeTurnovers: 12,
      awayTurnovers: 15,
      homeFouls: 18,
      awayFouls: 20,
      homeFgMade: 42,
      awayFgMade: 40,
      homeFgAttempted: 88,
      awayFgAttempted: 85,
      homeThreeMade: 12,
      awayThreeMade: 15,
      homeThreeAttempted: 32,
      awayThreeAttempted: 38,
      homeFtMade: 19,
      awayFtMade: 15,
      homeFtAttempted: 24,
      awayFtAttempted: 20,
      players: {
        home: [
          { name: 'LeBron James', points: 28, rebounds: 10, assists: 8, minutes: 35 },
          { name: 'Anthony Davis', points: 25, rebounds: 12, assists: 3, minutes: 32 },
          { name: 'Austin Reaves', points: 18, rebounds: 5, assists: 6, minutes: 28 },
          { name: 'D\'Angelo Russell', points: 15, rebounds: 3, assists: 7, minutes: 30 },
          { name: 'Rui Hachimura', points: 12, rebounds: 8, assists: 2, minutes: 25 }
        ],
        away: [
          { name: 'Stephen Curry', points: 32, rebounds: 6, assists: 8, minutes: 36 },
          { name: 'Klay Thompson', points: 22, rebounds: 4, assists: 3, minutes: 34 },
          { name: 'Andrew Wiggins', points: 20, rebounds: 8, assists: 2, minutes: 32 },
          { name: 'Draymond Green', points: 15, rebounds: 7, assists: 6, minutes: 30 },
          { name: 'Jonathan Kuminga', points: 21, rebounds: 5, assists: 4, minutes: 28 }
        ]
      }
    }
  },
  {
    id: '2',
    homeTeam: 'Celtics',
    awayTeam: 'Heat',
    homeScore: 102,
    awayScore: 98,
    date: '2024-02-28',
    stats: {
      homePoints: 102,
      awayPoints: 98,
      homeRebounds: 42,
      awayRebounds: 40,
      homeAssists: 22,
      awayAssists: 20,
      homeSteals: 7,
      awaySteals: 9,
      homeBlocks: 4,
      awayBlocks: 2,
      homeTurnovers: 14,
      awayTurnovers: 11,
      homeFouls: 22,
      awayFouls: 19,
      homeFgMade: 38,
      awayFgMade: 36,
      homeFgAttempted: 82,
      awayFgAttempted: 80,
      homeThreeMade: 10,
      awayThreeMade: 8,
      homeThreeAttempted: 28,
      awayThreeAttempted: 25,
      homeFtMade: 16,
      awayFtMade: 18,
      homeFtAttempted: 20,
      awayFtAttempted: 22,
      players: {
        home: [
          { name: 'Jaylen Brown', points: 24, rebounds: 8, assists: 5, minutes: 34 },
          { name: 'Jayson Tatum', points: 26, rebounds: 9, assists: 7, minutes: 36 },
          { name: 'Al Horford', points: 12, rebounds: 7, assists: 3, minutes: 28 },
          { name: 'Jrue Holiday', points: 18, rebounds: 4, assists: 6, minutes: 32 },
          { name: 'Derrick White', points: 22, rebounds: 3, assists: 1, minutes: 30 }
        ],
        away: [
          { name: 'Jimmy Butler', points: 28, rebounds: 10, assists: 4, minutes: 35 },
          { name: 'Bam Adebayo', points: 20, rebounds: 12, assists: 3, minutes: 33 },
          { name: 'Tyler Herro', points: 18, rebounds: 5, assists: 6, minutes: 31 },
          { name: 'Kyle Lowry', points: 15, rebounds: 4, assists: 7, minutes: 29 },
          { name: 'Duncan Robinson', points: 17, rebounds: 2, assists: 0, minutes: 27 }
        ]
      }
    }
  },
  {
    id: '3',
    homeTeam: 'Nets',
    awayTeam: '76ers',
    homeScore: 88,
    awayScore: 95,
    date: '2024-02-27',
    stats: {
      homePoints: 88,
      awayPoints: 95,
      homeRebounds: 35,
      awayRebounds: 48,
      homeAssists: 18,
      awayAssists: 30,
      homeSteals: 6,
      awaySteals: 11,
      homeBlocks: 3,
      awayBlocks: 7,
      homeTurnovers: 16,
      awayTurnovers: 10,
      homeFouls: 25,
      awayFouls: 18,
      homeFgMade: 32,
      awayFgMade: 35,
      homeFgAttempted: 78,
      awayFgAttempted: 82,
      homeThreeMade: 8,
      awayThreeMade: 12,
      homeThreeAttempted: 26,
      awayThreeAttempted: 32,
      homeFtMade: 16,
      awayFtMade: 13,
      homeFtAttempted: 20,
      awayFtAttempted: 18,
      players: {
        home: [
          { name: 'Kevin Durant', points: 25, rebounds: 8, assists: 5, minutes: 35 },
          { name: 'Kyrie Irving', points: 22, rebounds: 5, assists: 6, minutes: 33 },
          { name: 'Ben Simmons', points: 8, rebounds: 10, assists: 7, minutes: 28 },
          { name: 'James Harden', points: 18, rebounds: 6, assists: 8, minutes: 32 },
          { name: 'LaMarcus Aldridge', points: 15, rebounds: 6, assists: 2, minutes: 26 }
        ],
        away: [
          { name: 'Joel Embiid', points: 30, rebounds: 15, assists: 4, minutes: 36 },
          { name: 'James Harden', points: 25, rebounds: 8, assists: 10, minutes: 34 },
          { name: 'Tobias Harris', points: 20, rebounds: 7, assists: 3, minutes: 32 },
          { name: 'Tyrese Maxey', points: 12, rebounds: 4, assists: 8, minutes: 30 },
          { name: 'Danny Green', points: 8, rebounds: 3, assists: 5, minutes: 24 }
        ]
      }
    }
  },
  {
    id: '4',
    homeTeam: 'Bucks',
    awayTeam: 'Knicks',
    homeScore: 118,
    awayScore: 112,
    date: '2024-02-26',
    stats: {
      homePoints: 118,
      awayPoints: 112,
      homeRebounds: 52,
      awayRebounds: 45,
      homeAssists: 25,
      awayAssists: 22,
      homeSteals: 9,
      awaySteals: 7,
      homeBlocks: 6,
      awayBlocks: 4,
      homeTurnovers: 13,
      awayTurnovers: 16,
      homeFouls: 20,
      awayFouls: 23,
      homeFgMade: 44,
      awayFgMade: 42,
      homeFgAttempted: 90,
      awayFgAttempted: 88,
      homeThreeMade: 14,
      awayThreeMade: 11,
      homeThreeAttempted: 35,
      awayThreeAttempted: 30,
      homeFtMade: 16,
      awayFtMade: 17,
      homeFtAttempted: 22,
      awayFtAttempted: 25,
      players: {
        home: [
          { name: 'Giannis Antetokounmpo', points: 32, rebounds: 14, assists: 6, minutes: 38 },
          { name: 'Khris Middleton', points: 24, rebounds: 8, assists: 5, minutes: 34 },
          { name: 'Jrue Holiday', points: 18, rebounds: 6, assists: 8, minutes: 32 },
          { name: 'Brook Lopez', points: 16, rebounds: 10, assists: 2, minutes: 30 },
          { name: 'Damian Lillard', points: 28, rebounds: 4, assists: 4, minutes: 36 }
        ],
        away: [
          { name: 'Julius Randle', points: 28, rebounds: 12, assists: 4, minutes: 35 },
          { name: 'Jalen Brunson', points: 26, rebounds: 5, assists: 8, minutes: 37 },
          { name: 'RJ Barrett', points: 22, rebounds: 7, assists: 3, minutes: 33 },
          { name: 'Donte DiVincenzo', points: 18, rebounds: 6, assists: 4, minutes: 31 },
          { name: 'Josh Hart', points: 18, rebounds: 8, assists: 3, minutes: 29 }
        ]
      }
    }
  },
  {
    id: '5',
    homeTeam: 'Suns',
    awayTeam: 'Clippers',
    homeScore: 105,
    awayScore: 98,
    date: '2024-02-25',
    stats: {
      homePoints: 105,
      awayPoints: 98,
      homeRebounds: 48,
      awayRebounds: 42,
      homeAssists: 24,
      awayAssists: 20,
      homeSteals: 8,
      awaySteals: 5,
      homeBlocks: 4,
      awayBlocks: 2,
      homeTurnovers: 11,
      awayTurnovers: 14,
      homeFouls: 19,
      awayFouls: 21,
      homeFgMade: 39,
      awayFgMade: 36,
      homeFgAttempted: 84,
      awayFgAttempted: 82,
      homeThreeMade: 13,
      awayThreeMade: 10,
      homeThreeAttempted: 34,
      awayThreeAttempted: 28,
      homeFtMade: 14,
      awayFtMade: 16,
      homeFtAttempted: 18,
      awayFtAttempted: 20,
      players: {
        home: [
          { name: 'Kevin Durant', points: 28, rebounds: 10, assists: 5, minutes: 36 },
          { name: 'Devin Booker', points: 26, rebounds: 6, assists: 6, minutes: 35 },
          { name: 'Bradley Beal', points: 22, rebounds: 8, assists: 4, minutes: 34 },
          { name: 'Deandre Ayton', points: 14, rebounds: 12, assists: 2, minutes: 32 },
          { name: 'Chris Paul', points: 15, rebounds: 4, assists: 7, minutes: 28 }
        ],
        away: [
          { name: 'Kawhi Leonard', points: 30, rebounds: 9, assists: 4, minutes: 37 },
          { name: 'Paul George', points: 25, rebounds: 8, assists: 5, minutes: 36 },
          { name: 'James Harden', points: 18, rebounds: 7, assists: 8, minutes: 33 },
          { name: 'Russell Westbrook', points: 12, rebounds: 10, assists: 6, minutes: 31 },
          { name: 'Ivica Zubac', points: 13, rebounds: 8, assists: 2, minutes: 29 }
        ]
      }
    }
  },
  {
    id: '6',
    homeTeam: 'Mavericks',
    awayTeam: 'Thunder',
    homeScore: 122,
    awayScore: 115,
    date: '2024-02-24',
    stats: {
      homePoints: 122,
      awayPoints: 115,
      homeRebounds: 46,
      awayRebounds: 44,
      homeAssists: 28,
      awayAssists: 25,
      homeSteals: 10,
      awaySteals: 8,
      homeBlocks: 5,
      awayBlocks: 3,
      homeTurnovers: 12,
      awayTurnovers: 15,
      homeFouls: 17,
      awayFouls: 20,
      homeFgMade: 45,
      awayFgMade: 42,
      homeFgAttempted: 92,
      awayFgAttempted: 88,
      homeThreeMade: 15,
      awayThreeMade: 12,
      homeThreeAttempted: 38,
      awayThreeAttempted: 32,
      homeFtMade: 17,
      awayFtMade: 19,
      homeFtAttempted: 22,
      awayFtAttempted: 25,
      players: {
        home: [
          { name: 'Luka Dončić', points: 35, rebounds: 12, assists: 8, minutes: 38 },
          { name: 'Kyrie Irving', points: 28, rebounds: 6, assists: 5, minutes: 36 },
          { name: 'P.J. Washington', points: 18, rebounds: 8, assists: 2, minutes: 32 },
          { name: 'Dereck Lively II', points: 12, rebounds: 10, assists: 1, minutes: 30 },
          { name: 'Derrick Jones Jr.', points: 14, rebounds: 4, assists: 3, minutes: 28 }
        ],
        away: [
          { name: 'Shai Gilgeous-Alexander', points: 32, rebounds: 8, assists: 6, minutes: 37 },
          { name: 'Jalen Williams', points: 22, rebounds: 7, assists: 4, minutes: 34 },
          { name: 'Josh Giddey', points: 18, rebounds: 9, assists: 5, minutes: 32 },
          { name: 'Chet Holmgren', points: 16, rebounds: 12, assists: 2, minutes: 35 },
          { name: 'Luguentz Dort', points: 15, rebounds: 3, assists: 3, minutes: 31 }
        ]
      }
    }
  },
  {
    id: '7',
    homeTeam: 'Nuggets',
    awayTeam: 'Timberwolves',
    homeScore: 108,
    awayScore: 102,
    date: '2024-02-23',
    stats: {
      homePoints: 108,
      awayPoints: 102,
      homeRebounds: 49,
      awayRebounds: 43,
      homeAssists: 26,
      awayAssists: 22,
      homeSteals: 7,
      awaySteals: 9,
      homeBlocks: 5,
      awayBlocks: 4,
      homeTurnovers: 13,
      awayTurnovers: 11,
      homeFouls: 21,
      awayFouls: 18,
      homeFgMade: 40,
      awayFgMade: 38,
      homeFgAttempted: 86,
      awayFgAttempted: 84,
      homeThreeMade: 11,
      awayThreeMade: 9,
      homeThreeAttempted: 30,
      awayThreeAttempted: 26,
      homeFtMade: 17,
      awayFtMade: 17,
      homeFtAttempted: 22,
      awayFtAttempted: 20,
      players: {
        home: [
          { name: 'Nikola Jokić', points: 28, rebounds: 16, assists: 7, minutes: 36 },
          { name: 'Jamal Murray', points: 24, rebounds: 6, assists: 8, minutes: 35 },
          { name: 'Aaron Gordon', points: 18, rebounds: 9, assists: 3, minutes: 32 },
          { name: 'Michael Porter Jr.', points: 20, rebounds: 8, assists: 2, minutes: 34 },
          { name: 'Kentavious Caldwell-Pope', points: 18, rebounds: 4, assists: 1, minutes: 31 }
        ],
        away: [
          { name: 'Anthony Edwards', points: 30, rebounds: 8, assists: 5, minutes: 37 },
          { name: 'Karl-Anthony Towns', points: 26, rebounds: 12, assists: 3, minutes: 35 },
          { name: 'Rudy Gobert', points: 14, rebounds: 14, assists: 1, minutes: 33 },
          { name: 'Mike Conley', points: 16, rebounds: 4, assists: 8, minutes: 32 },
          { name: 'Jaden McDaniels', points: 16, rebounds: 5, assists: 5, minutes: 30 }
        ]
      }
    }
  },
  {
    id: '8',
    homeTeam: 'Warriors',
    awayTeam: 'Kings',
    homeScore: 125,
    awayScore: 118,
    date: '2024-02-22',
    stats: {
      homePoints: 125,
      awayPoints: 118,
      homeRebounds: 47,
      awayRebounds: 41,
      homeAssists: 32,
      awayAssists: 28,
      homeSteals: 11,
      awaySteals: 6,
      homeBlocks: 4,
      awayBlocks: 2,
      homeTurnovers: 14,
      awayTurnovers: 17,
      homeFouls: 19,
      awayFouls: 22,
      homeFgMade: 46,
      awayFgMade: 43,
      homeFgAttempted: 94,
      awayFgAttempted: 90,
      homeThreeMade: 16,
      awayThreeMade: 13,
      homeThreeAttempted: 42,
      awayThreeAttempted: 36,
      homeFtMade: 17,
      awayFtMade: 19,
      homeFtAttempted: 24,
      awayFtAttempted: 26,
      players: {
        home: [
          { name: 'Stephen Curry', points: 38, rebounds: 8, assists: 10, minutes: 38 },
          { name: 'Klay Thompson', points: 26, rebounds: 6, assists: 4, minutes: 35 },
          { name: 'Andrew Wiggins', points: 22, rebounds: 9, assists: 3, minutes: 34 },
          { name: 'Draymond Green', points: 16, rebounds: 8, assists: 8, minutes: 32 },
          { name: 'Jonathan Kuminga', points: 23, rebounds: 6, assists: 2, minutes: 31 }
        ],
        away: [
          { name: 'De\'Aaron Fox', points: 32, rebounds: 6, assists: 8, minutes: 36 },
          { name: 'Domantas Sabonis', points: 24, rebounds: 14, assists: 6, minutes: 35 },
          { name: 'Kevin Huerter', points: 18, rebounds: 5, assists: 3, minutes: 33 },
          { name: 'Harrison Barnes', points: 20, rebounds: 7, assists: 2, minutes: 32 },
          { name: 'Malik Monk', points: 24, rebounds: 4, assists: 4, minutes: 30 }
        ]
      }
    }
  },
  {
    id: '9',
    homeTeam: 'Pelicans',
    awayTeam: 'Grizzlies',
    homeScore: 115,
    awayScore: 109,
    date: '2024-02-21',
    stats: {
      homePoints: 115,
      awayPoints: 109,
      homeRebounds: 50,
      awayRebounds: 45,
      homeAssists: 27,
      awayAssists: 23,
      homeSteals: 9,
      awaySteals: 7,
      homeBlocks: 6,
      awayBlocks: 3,
      homeTurnovers: 15,
      awayTurnovers: 12,
      homeFouls: 20,
      awayFouls: 24,
      homeFgMade: 43,
      awayFgMade: 40,
      homeFgAttempted: 89,
      awayFgAttempted: 86,
      homeThreeMade: 12,
      awayThreeMade: 10,
      homeThreeAttempted: 33,
      awayThreeAttempted: 29,
      homeFtMade: 17,
      awayFtMade: 19,
      homeFtAttempted: 22,
      awayFtAttempted: 26,
      players: {
        home: [
          { name: 'Zion Williamson', points: 30, rebounds: 12, assists: 4, minutes: 35 },
          { name: 'Brandon Ingram', points: 26, rebounds: 8, assists: 6, minutes: 36 },
          { name: 'CJ McCollum', points: 22, rebounds: 6, assists: 5, minutes: 34 },
          { name: 'Jonas Valančiūnas', points: 16, rebounds: 12, assists: 2, minutes: 32 },
          { name: 'Herbert Jones', points: 14, rebounds: 7, assists: 3, minutes: 31 }
        ],
        away: [
          { name: 'Ja Morant', points: 28, rebounds: 8, assists: 8, minutes: 37 },
          { name: 'Desmond Bane', points: 24, rebounds: 6, assists: 4, minutes: 35 },
          { name: 'Jaren Jackson Jr.', points: 22, rebounds: 10, assists: 2, minutes: 34 },
          { name: 'Steven Adams', points: 12, rebounds: 11, assists: 1, minutes: 33 },
          { name: 'Dillon Brooks', points: 15, rebounds: 5, assists: 3, minutes: 32 }
        ]
      }
    }
  }
]

export default function DashboardTabs() {
  const [activeTab, setActiveTab] = useState<Tab>('view')
  const [selectedGame, setSelectedGame] = useState<string | null>(null)
  const [reviewClip, setReviewClip] = useState<FootageClip | null>(null)
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadedVideos, setUploadedVideos] = useState<UploadedVideo[]>([])
  const [uploadedVideosLoading, setUploadedVideosLoading] = useState(false)
  const [uploadedVideosError, setUploadedVideosError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const acceptedFormats = '.mp4,.mov,.avi,.mkv,.webm,.m4v'
  const acceptedExtensions = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v'])

  const isVideoFile = (file: File) => {
    if (file.type.startsWith('video/')) return true
    const extension = file.name.split('.').pop()?.toLowerCase()
    return !!extension && acceptedExtensions.has(extension)
  }

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

  const removeUpload = (id: string) => {
    setUploads((prev) => prev.filter((item) => item.id !== id))
  }

  const confirmUpload = async () => {
    const queuedItems = uploads.filter((item) => item.status === 'queued')
    if (queuedItems.length === 0) return

    setIsUploading(true)
    setUploads((prev) =>
      prev.map((item) =>
        item.status === 'queued'
          ? { ...item, status: 'uploading', message: 'Uploading...' }
          : item
      )
    )

    const uploadResults = await Promise.all(
      queuedItems.map(async (item) => {
        const formData = new FormData()
        formData.append('file', item.file)

        try {
          const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
          })

          const payload = (await response.json()) as {
            key?: string
            url?: string
            error?: string
          }

          if (!response.ok) {
            return {
              id: item.id,
              status: 'failed' as UploadStatus,
              message: payload.error ?? 'Upload failed',
              uploadedUrl: undefined,
            }
          }

          return {
            id: item.id,
            status: 'uploaded' as UploadStatus,
            message: 'Uploaded successfully',
            uploadedUrl: payload.url ?? undefined,
          }
        } catch {
          return {
            id: item.id,
            status: 'failed' as UploadStatus,
            message: 'Upload failed due to a network error',
            uploadedUrl: undefined,
          }
        }
      })
    )

    const resultsById = new Map(uploadResults.map((result) => [result.id, result]))

    setUploads((prev) =>
      prev.map((item) => {
        const result = resultsById.get(item.id)
        if (!result) return item
        return {
          ...item,
          status: result.status,
          message: result.message,
          uploadedUrl: result.uploadedUrl,
        }
      })
    )
    setIsUploading(false)
  }

  useEffect(() => {
    if (activeTab !== 'past') return

    let cancelled = false

    const loadUploadedVideos = async () => {
      setUploadedVideosLoading(true)
      setUploadedVideosError(null)

      try {
        const response = await fetch('/api/upload/list', { method: 'GET' })
        const payload = (await response.json()) as {
          uploads?: UploadedVideo[]
          error?: string
        }

        if (!response.ok) {
          throw new Error(payload.error ?? 'Unable to fetch uploaded videos')
        }

        if (!cancelled) {
          setUploadedVideos(payload.uploads ?? [])
        }
      } catch (error) {
        if (!cancelled) {
          const message =
            error instanceof Error ? error.message : 'Unable to fetch uploaded videos'
          setUploadedVideosError(message)
          setUploadedVideos([])
        }
      } finally {
        if (!cancelled) setUploadedVideosLoading(false)
      }
    }

    void loadUploadedVideos()

    return () => {
      cancelled = true
    }
  }, [activeTab])

  return (
    <main className="flex-1 flex flex-col px-8 pt-10 pb-16 max-w-[1280px] w-full mx-auto">

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-[rgba(200,136,58,0.15)] mb-10">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-5 pb-3.5 pt-1 font-body text-[0.78rem] tracking-[0.12em] uppercase transition-colors duration-200 border-b-[1.5px] -mb-px cursor-pointer ${
              activeTab === t.id
                ? 'text-brand border-brand'
                : 'text-muted border-transparent hover:text-offwhite/70'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      <div className="animate-fade-up" key={activeTab}>

        {/* ── View Footage (playback library — separate from upload ingest) ── */}
        {activeTab === 'view' && (
          <FootageViewTab reviewClip={reviewClip} />
        )}

        {/* ── Upload ── */}
        {activeTab === 'upload' && (
          <div className="flex flex-col">
            <h2 className="font-display text-offwhite text-[clamp(1.6rem,3vw,2.2rem)] tracking-[0.04em] mb-2">
              Upload New Footage
            </h2>
            <p className="text-[0.84rem] text-muted font-light mb-8">
              Send game film to ingest. Viewing uses a different pipeline — open{' '}
              <span className="text-muted/80">View Footage</span> once processing finishes.
            </p>

            {/* Upload zone */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setIsDragging(false)
                queueFiles(event.dataTransfer.files)
              }}
              className={`w-full border border-dashed rounded-sm p-14 text-center transition-colors duration-200 mb-6 cursor-pointer ${
                isDragging
                  ? 'border-brand bg-[rgba(200,136,58,0.05)]'
                  : 'border-[rgba(200,136,58,0.28)] bg-[rgba(200,136,58,0.02)] hover:border-brand hover:bg-[rgba(200,136,58,0.05)]'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={acceptedFormats}
                multiple
                className="hidden"
                onChange={(event) => {
                  queueFiles(event.target.files)
                  event.target.value = ''
                }}
              />
              <div className="font-display text-[1.3rem] tracking-[0.08em] text-offwhite mb-2">
                Drop footage here or click to browse
              </div>
              <div className="text-[0.76rem] text-muted font-light mb-4">
                Game film, practice sessions, highlight cuts
              </div>
              <div className="flex gap-2 justify-center">
                {['MP4', 'MOV', 'AVI', 'MKV'].map((fmt) => (
                  <span
                    key={fmt}
                    className="text-[0.62rem] tracking-[0.12em] px-2.5 py-1 border border-[rgba(200,136,58,0.18)] rounded-sm text-muted"
                  >
                    {fmt}
                  </span>
                ))}
              </div>
            </button>

            {uploads.length > 0 && (
              <div className="mb-6 border border-[rgba(200,136,58,0.12)] rounded-sm bg-[rgba(200,136,58,0.015)]">
                <div className="flex items-center justify-between px-4 py-3 border-b border-[rgba(200,136,58,0.12)]">
                  <p className="text-[0.74rem] tracking-[0.12em] uppercase text-muted">
                    Selected files
                  </p>
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
                    <div key={item.id} className="px-4 py-3 flex items-center justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-sm text-offwhite truncate">{item.file.name}</p>
                        <p
                          className={`text-[0.7rem] mt-0.5 ${
                            item.status === 'invalid'
                              ? 'text-red-300/80'
                              : item.status === 'failed'
                                ? 'text-red-300/80'
                              : item.status === 'uploaded'
                                ? 'text-green-300/80'
                                : 'text-muted'
                          }`}
                        >
                          {item.message}
                        </p>
                        {item.uploadedUrl && (
                          <a
                            href={item.uploadedUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-block mt-1 text-[0.68rem] text-brand hover:text-brand/80 transition-colors duration-200"
                          >
                            Open uploaded file
                          </a>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => removeUpload(item.id)}
                        className="text-[0.64rem] tracking-[0.1em] uppercase text-muted hover:text-offwhite transition-colors duration-200"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recent uploads placeholder */}
            <p className="text-[0.74rem] text-muted/50 font-light">
              <RoleSwitch
                coach="No plays saved. Even Phil Jackson wrote things down."
                fan="Nothing here. Emptier than Cleveland's trophy case before 2016."
                player="No footage yet. LeBron didn't become LeBron by skipping film."
              />
            </p>
          </div>
        )}

        {/* ── Past Games ── */}
        {activeTab === 'past' && (
          <div className="flex flex-col">
            <h2 className="font-display text-offwhite text-[clamp(1.6rem,3vw,2.2rem)] tracking-[0.04em] mb-2">
              Past Games
            </h2>
            <p className="text-[0.84rem] text-muted font-light mb-8">
              Track previous games and pull historical stats.
            </p>

            {uploadedVideosLoading && (
              <p className="text-[0.74rem] text-muted/70 font-light mb-4">
                Loading uploaded videos...
              </p>
            )}

            {uploadedVideosError && (
              <p className="text-[0.74rem] text-red-300/80 font-light mb-4">{uploadedVideosError}</p>
            )}

            {selectedGame ? (
              // Detailed view for selected game
              (() => {
                const game = MOCK_GAMES.find(g => g.id === selectedGame)
                if (!game) return null
                return (
                  <div>
                    <button
                      onClick={() => setSelectedGame(null)}
                      className="mb-6 text-muted hover:text-offwhite transition-colors duration-200 text-sm tracking-widest uppercase"
                    >
                      ← Back to Games
                    </button>
                    
                    <div className="border border-[rgba(200,136,58,0.12)] rounded-sm bg-[rgba(200,136,58,0.015)] p-6">
                      <div className="text-center mb-6">
                        <div className="text-sm text-muted font-light mb-2">{game.date}</div>
                        <div className="flex justify-center items-center gap-4">
                          <div className="text-left">
                            <div className={`text-4xl font-display text-offwhite`}>{game.awayTeam} vs {game.homeTeam}</div>
                          </div>
                          <div className="text-4xl font-display text-offwhite">
                            {game.awayScore} - {game.homeScore}
                          </div>
                        </div>
                      </div>

                      {/* Open this game in View Footage (playback tab) */}
                      <div className="mb-8 flex flex-col items-center gap-3">
                        <button
                          type="button"
                          onClick={() => {
                            setReviewClip(gameToReviewClip(game))
                            setActiveTab('view')
                          }}
                          className="font-body text-[0.78rem] tracking-[0.14em] uppercase px-8 py-3.5 rounded-sm border border-brand/50 bg-brand/15 text-offwhite hover:bg-brand/25 hover:border-brand transition-colors duration-200 cursor-pointer"
                        >
                          Review video
                        </button>
                        {!game.videoUrl && (
                          <p className="text-[0.72rem] text-muted/60 font-light text-center max-w-sm">
                            No stream is linked for this game yet. You&apos;ll still open View
                            Footage; add a video URL on the game record when playback is available.
                          </p>
                        )}
                      </div>

                      {game.stats && (
                        <div>
                          <h4 className="font-display text-offwhite text-lg mb-6 tracking-wider uppercase text-center">Team Statistics</h4>
                          
                          {/* Team Stats Comparison */}
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                            {/* Away Team Stats */}
                            <div className="border border-[rgba(200,136,58,0.12)] rounded-sm p-4 bg-[rgba(200,136,58,0.02)]">
                              <h5 className="font-body text-offwhite text-md mb-4 tracking-wider uppercase text-center">{game.awayTeam}</h5>
                              <div className="space-y-3">
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Points</span>
                                  <span className="font-body text-offwhite">{game.stats.awayPoints}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Rebounds</span>
                                  <span className="font-body text-offwhite">{game.stats.awayRebounds}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Assists</span>
                                  <span className="font-body text-offwhite">{game.stats.awayAssists}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Steals</span>
                                  <span className="font-body text-offwhite">{game.stats.awaySteals}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Blocks</span>
                                  <span className="font-body text-offwhite">{game.stats.awayBlocks}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Turnovers</span>
                                  <span className="font-body text-offwhite">{game.stats.awayTurnovers}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Fouls</span>
                                  <span className="font-body text-offwhite">{game.stats.awayFouls}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FG Made/Att</span>
                                  <span className="font-body text-offwhite">{game.stats.awayFgMade}/{game.stats.awayFgAttempted}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FG %</span>
                                  <span className="font-body text-offwhite">{((game.stats.awayFgMade / game.stats.awayFgAttempted) * 100).toFixed(1)}%</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">3PT Made/Att</span>
                                  <span className="font-body text-offwhite">{game.stats.awayThreeMade}/{game.stats.awayThreeAttempted}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">3PT %</span>
                                  <span className="font-body text-offwhite">{((game.stats.awayThreeMade / game.stats.awayThreeAttempted) * 100).toFixed(1)}%</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FT Made/Att</span>
                                  <span className="font-body text-offwhite">{game.stats.awayFtMade}/{game.stats.awayFtAttempted}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FT %</span>
                                  <span className="font-body text-offwhite">{((game.stats.awayFtMade / game.stats.awayFtAttempted) * 100).toFixed(1)}%</span>
                                </div>
                              </div>
                            </div>

                            {/* Home Team Stats */}
                            <div className="border border-[rgba(200,136,58,0.12)] rounded-sm p-4 bg-[rgba(200,136,58,0.02)]">
                              <h5 className="font-body text-offwhite text-md mb-4 tracking-wider uppercase text-center">{game.homeTeam}</h5>
                              <div className="space-y-3">
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Points</span>
                                  <span className="font-body text-offwhite">{game.stats.homePoints}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Rebounds</span>
                                  <span className="font-body text-offwhite">{game.stats.homeRebounds}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Assists</span>
                                  <span className="font-body text-offwhite">{game.stats.homeAssists}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Steals</span>
                                  <span className="font-body text-offwhite">{game.stats.homeSteals}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Blocks</span>
                                  <span className="font-body text-offwhite">{game.stats.homeBlocks}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Turnovers</span>
                                  <span className="font-body text-offwhite">{game.stats.homeTurnovers}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">Fouls</span>
                                  <span className="font-body text-offwhite">{game.stats.homeFouls}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FG Made/Att</span>
                                  <span className="font-body text-offwhite">{game.stats.homeFgMade}/{game.stats.homeFgAttempted}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FG %</span>
                                  <span className="font-body text-offwhite">{((game.stats.homeFgMade / game.stats.homeFgAttempted) * 100).toFixed(1)}%</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">3PT Made/Att</span>
                                  <span className="font-body text-offwhite">{game.stats.homeThreeMade}/{game.stats.homeThreeAttempted}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">3PT %</span>
                                  <span className="font-body text-offwhite">{((game.stats.homeThreeMade / game.stats.homeThreeAttempted) * 100).toFixed(1)}%</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FT Made/Att</span>
                                  <span className="font-body text-offwhite">{game.stats.homeFtMade}/{game.stats.homeFtAttempted}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted text-sm">FT %</span>
                                  <span className="font-body text-offwhite">{((game.stats.homeFtMade / game.stats.homeFtAttempted) * 100).toFixed(1)}%</span>
                                </div>
                              </div>
                            </div>
                          </div>

                          {game.stats.players && (
                            <div className="space-y-6">
                              {/* Away Team Players */}
                              <div>
                                <h5 className="font-display text-offwhite text-md mb-3 tracking-wider uppercase">{game.awayTeam} Players</h5>
                                <div className="overflow-x-auto">
                                  <table className="w-full text-sm">
                                    <thead>
                                      <tr className="border-b border-[rgba(200,136,58,0.12)]">
                                        <th className="text-left py-2 text-muted font-light w-1/2">Player</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">PTS</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">REB</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">AST</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">MIN</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {game.stats.players.away.map((player, index) => (
                                        <tr key={index} className="border-b border-[rgba(200,136,58,0.06)]">
                                          <td className="py-2 text-offwhite font-body">{player.name}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.points}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.rebounds}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.assists}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.minutes}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>

                              {/* Home Team Players */}
                              <div>
                                <h5 className="font-display text-offwhite text-md mb-3 tracking-wider uppercase">{game.homeTeam} Players</h5>
                                <div className="overflow-x-auto">
                                  <table className="w-full text-sm">
                                    <thead>
                                      <tr className="border-b border-[rgba(200,136,58,0.12)]">
                                        <th className="text-left py-2 text-muted font-light w-1/2">Player</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">PTS</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">REB</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">AST</th>
                                        <th className="text-center py-2 text-muted font-light w-1/8">MIN</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {game.stats.players.home.map((player, index) => (
                                        <tr key={index} className="border-b border-[rgba(200,136,58,0.06)]">
                                          <td className="py-2 text-offwhite font-body">{player.name}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.points}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.rebounds}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.assists}</td>
                                          <td className="py-2 text-center text-offwhite font-body">{player.minutes}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()
            ) : (
              // Games Grid
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {uploadedVideos.map((video) => (
                  <div
                    key={video.key}
                    className="border border-brand/30 rounded-sm bg-brand/5 overflow-hidden cursor-pointer hover:bg-brand/10 transition-colors duration-200"
                    onClick={() => {
                      setReviewClip({
                        id: `uploaded-${video.key}`,
                        title: video.name,
                        createdAt: video.lastModified ?? new Date().toISOString(),
                        playbackUrl: video.url,
                      })
                      setActiveTab('view')
                    }}
                  >
                    <div className="p-4">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-sm text-muted font-light">
                          {video.lastModified
                            ? new Date(video.lastModified).toLocaleDateString()
                            : 'Uploaded video'}
                        </span>
                        <span className="text-xs tracking-widest uppercase px-2 py-1 rounded-sm bg-brand/20 text-brand">
                          REVIEW VIDEO
                        </span>
                      </div>
                      <div className="text-left">
                        <div className="font-display text-lg text-offwhite truncate">{video.name}</div>
                        <div className="text-xs text-muted mt-1">
                          {(video.size / (1024 * 1024)).toFixed(1)} MB
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
                {MOCK_GAMES.map((game) => (
                  <div 
                    key={game.id} 
                    className="border border-[rgba(200,136,58,0.12)] rounded-sm bg-[rgba(200,136,58,0.015)] overflow-hidden cursor-pointer hover:bg-[rgba(200,136,58,0.03)] transition-colors duration-200"
                    onClick={() => setSelectedGame(game.id)}
                  >
                    <div className="p-4">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-sm text-muted font-light">{game.date}</span>
                        <span className="text-xs tracking-widest uppercase px-2 py-1 rounded-sm bg-muted/20 text-muted">
                          VIEW STATS
                        </span>
                      </div>
                      <div className="flex justify-between items-center">
                        <div className="text-left">
                          <div className={`font-display text-lg ${game.awayScore > game.homeScore ? 'text-offwhite' : 'text-muted'}`}>{game.awayTeam}</div>
                          <div className={`font-display text-lg ${game.awayScore > game.homeScore ? 'text-muted' : 'text-offwhite'}`}>vs {game.homeTeam}</div>
                        </div>
                        <div className="text-right">
                          <div className={`font-display text-lg ${game.awayScore > game.homeScore ? 'text-offwhite' : 'text-muted'}`}>{game.awayScore}</div>
                          <div className={`font-display text-lg ${game.awayScore > game.homeScore ? 'text-muted' : 'text-offwhite'}`}>{game.homeScore}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  )
}
