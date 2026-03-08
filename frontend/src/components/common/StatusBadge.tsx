// src/components/common/StatusBadge.tsx
// Small pill badge indicating bed / connection status.

import React from 'react'

export type BadgeVariant = 'live' | 'stale' | 'alert' | 'warmup' | 'disconnected'

const STYLES: Record<BadgeVariant, string> = {
  live:         'bg-gray-900 text-white',
  stale:        'bg-gray-300 text-gray-700',
  alert:        'bg-red-500 text-white font-bold',
  warmup:       'bg-gray-200 text-gray-600',
  disconnected: 'bg-gray-200 text-gray-500',
}

const LABELS: Record<BadgeVariant, string> = {
  live:         'LIVE',
  stale:        'STALE',
  alert:        'ALERT',
  warmup:       'WARMUP',
  disconnected: 'DISCONNECTED',
}

interface Props {
  variant: BadgeVariant
  label?: string
  pulse?: boolean
}

export const StatusBadge: React.FC<Props> = ({ variant, label, pulse }) => (
  <span
    className={[
      'inline-flex items-center rounded px-1.5 py-0.5 text-xs tracking-wide',
      STYLES[variant],
      pulse || variant === 'live' ? 'animate-pulse' : '',
    ].join(' ')}
  >
    {label ?? LABELS[variant]}
  </span>
)
