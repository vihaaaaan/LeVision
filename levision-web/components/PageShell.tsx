import type { ReactNode } from 'react'
import { ChatDockProvider } from '@/components/chat/ChatDockProvider'
import FloatingChat from '@/components/FloatingChat'

export default function PageShell({ children }: { children: ReactNode }) {
  return (
    <ChatDockProvider>
    <div className="relative min-h-screen bg-pitch overflow-hidden">

      {/* Radial amber glow — centered, low */}
      <div
        className="fixed inset-0 z-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 90% 55% at 50% 110%, rgba(200,136,58,0.13) 0%, transparent 70%)',
        }}
      />

      {/* Court — perspective-tilted top-down view, NBA-accurate geometry */}
      {/* Scale: 14 px / ft. Court 94×50 ft → 1316×700 px, offset x=62 y=100 */}
      {/* Left basket (136,450), Right basket (1305,450)                      */}
      <div
        className="fixed inset-0 z-0 pointer-events-none overflow-hidden"
        style={{ perspective: '1600px', perspectiveOrigin: '50% 48%' }}
      >
        <div
          style={{
            position: 'absolute',
            inset: '-18% -8%',
            transform: 'rotateX(20deg)',
            transformOrigin: '50% 58%',
            opacity: 0.17,
          }}
        >
          <svg
            viewBox="0 0 1440 900"
            preserveAspectRatio="xMidYMid slice"
            fill="none"
            style={{ width: '100%', height: '100%' }}
          >
            {/* Court floor tint */}
            <rect x="62" y="100" width="1316" height="700" fill="rgba(200,136,58,0.04)" />

            {/* ── Boundary & half-court ─────────────────────────────────── */}
            <rect x="62" y="100" width="1316" height="700" stroke="#c8883a" strokeWidth="2" />
            <line x1="720" y1="100" x2="720" y2="800" stroke="#c8883a" strokeWidth="2" />

            {/* Center circle + jump ball dot */}
            <circle cx="720" cy="450" r="84" stroke="#c8883a" strokeWidth="2" />
            <circle cx="720" cy="450" r="5" fill="#c8883a" fillOpacity="0.7" />

            {/* ── LEFT SIDE ────────────────────────────────────────────── */}

            {/* 3pt — corner straight lines */}
            <line x1="62" y1="142" x2="258" y2="142" stroke="#c8883a" strokeWidth="2" />
            <line x1="62" y1="758" x2="258" y2="758" stroke="#c8883a" strokeWidth="2" />
            {/* 3pt — arc (r≈332.5, center at left basket 136,450) */}
            <path d="M 258 142 A 332.5 332.5 0 0 1 258 758" stroke="#c8883a" strokeWidth="2" />

            {/* Paint / key */}
            <rect x="62" y="338" width="266" height="224" stroke="#c8883a" strokeWidth="2" />

            {/* Lane hash marks — top edge */}
            <line x1="160" y1="326" x2="160" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="216" y1="326" x2="216" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="258" y1="326" x2="258" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="300" y1="326" x2="300" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            {/* Lane hash marks — bottom edge */}
            <line x1="160" y1="562" x2="160" y2="574" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="216" y1="562" x2="216" y2="574" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="258" y1="562" x2="258" y2="574" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="300" y1="562" x2="300" y2="574" stroke="#c8883a" strokeWidth="1.5" />

            {/* Free throw circle — solid (court side) */}
            <path d="M 328 366 A 84 84 0 0 1 328 534" stroke="#c8883a" strokeWidth="2" />
            {/* Free throw circle — dashed (lane side) */}
            <path d="M 328 366 A 84 84 0 0 0 328 534" stroke="#c8883a" strokeWidth="1.5" strokeDasharray="7 11" />

            {/* Backboard */}
            <line x1="118" y1="408" x2="118" y2="492" stroke="#c8883a" strokeWidth="3" />
            {/* Basket ring */}
            <circle cx="136" cy="450" r="14" stroke="#c8883a" strokeWidth="1.5" />

            {/* Restricted area — arms + arc (r=56, center basket 136,450) */}
            <line x1="62"  y1="394" x2="136" y2="394" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="62"  y1="506" x2="136" y2="506" stroke="#c8883a" strokeWidth="1.5" />
            <path d="M 136 394 A 56 56 0 0 1 136 506" stroke="#c8883a" strokeWidth="1.5" />

            {/* ── RIGHT SIDE ───────────────────────────────────────────── */}

            {/* 3pt — corner straight lines */}
            <line x1="1182" y1="142" x2="1378" y2="142" stroke="#c8883a" strokeWidth="2" />
            <line x1="1182" y1="758" x2="1378" y2="758" stroke="#c8883a" strokeWidth="2" />
            {/* 3pt — arc (r≈332.5, center at right basket 1305,450) */}
            <path d="M 1182 142 A 332.5 332.5 0 0 0 1182 758" stroke="#c8883a" strokeWidth="2" />

            {/* Paint / key */}
            <rect x="1112" y="338" width="266" height="224" stroke="#c8883a" strokeWidth="2" />

            {/* Lane hash marks — top edge */}
            <line x1="1280" y1="326" x2="1280" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1224" y1="326" x2="1224" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1182" y1="326" x2="1182" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1140" y1="326" x2="1140" y2="338" stroke="#c8883a" strokeWidth="1.5" />
            {/* Lane hash marks — bottom edge */}
            <line x1="1280" y1="562" x2="1280" y2="574" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1224" y1="562" x2="1224" y2="574" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1182" y1="562" x2="1182" y2="574" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1140" y1="562" x2="1140" y2="574" stroke="#c8883a" strokeWidth="1.5" />

            {/* Free throw circle — solid (court side) */}
            <path d="M 1112 366 A 84 84 0 0 0 1112 534" stroke="#c8883a" strokeWidth="2" />
            {/* Free throw circle — dashed (lane side) */}
            <path d="M 1112 366 A 84 84 0 0 1 1112 534" stroke="#c8883a" strokeWidth="1.5" strokeDasharray="7 11" />

            {/* Backboard */}
            <line x1="1322" y1="408" x2="1322" y2="492" stroke="#c8883a" strokeWidth="3" />
            {/* Basket ring */}
            <circle cx="1305" cy="450" r="14" stroke="#c8883a" strokeWidth="1.5" />

            {/* Restricted area — arms + arc (r=56, center basket 1305,450) */}
            <line x1="1305" y1="394" x2="1378" y2="394" stroke="#c8883a" strokeWidth="1.5" />
            <line x1="1305" y1="506" x2="1378" y2="506" stroke="#c8883a" strokeWidth="1.5" />
            <path d="M 1305 394 A 56 56 0 0 0 1305 506" stroke="#c8883a" strokeWidth="1.5" />
          </svg>
        </div>
      </div>

      {/* Grain texture */}
      <div
        className="fixed inset-0 z-10 pointer-events-none opacity-[0.35]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.06'/%3E%3C/svg%3E")`,
        }}
      />

      {/* Scan line */}
      <div
        className="fixed left-0 right-0 h-px z-20 pointer-events-none animate-scan"
        style={{
          background: 'linear-gradient(90deg, transparent, #c8883a, transparent)',
          opacity: 0.4,
        }}
      />

      {/* Content */}
      <div className="relative z-30">
        {children}
      </div>

      <FloatingChat />
    </div>
    </ChatDockProvider>
  )
}
