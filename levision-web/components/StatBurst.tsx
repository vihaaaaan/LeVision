'use client'

import { useEffect, useRef, useState } from 'react'

interface Delta {
  id: number
  value: number
}

export default function StatBurst({ value, children }: { value: number; children: React.ReactNode }) {
  const prev = useRef(value)
  const [pop, setPop] = useState(false)
  const [deltas, setDeltas] = useState<Delta[]>([])
  const counter = useRef(0)

  useEffect(() => {
    const diff = value - prev.current
    if (diff > 0) {
      setPop(true)
      setTimeout(() => setPop(false), 300)
      const id = counter.current++
      setDeltas(d => [...d, { id, value: diff }])
      setTimeout(() => setDeltas(d => d.filter(x => x.id !== id)), 900)
    }
    prev.current = value
  }, [value])

  return (
    <div className="relative inline-block">
      <span style={{ display: 'inline-block', transform: pop ? 'scale(1.4)' : 'scale(1)', transition: 'transform 0.15s ease-out' }}>
        {children}
      </span>
      {deltas.map(d => (
        <span
          key={d.id}
          className="pointer-events-none absolute left-1/2 -top-1 text-[0.6rem] font-bold text-brand"
          style={{
            transform: 'translateX(-50%)',
            animation: 'statFloat 0.9s ease-out forwards',
          }}
        >
          +{d.value}
        </span>
      ))}
    </div>
  )
}
