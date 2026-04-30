import React, { useEffect, useState } from 'react'
import { formatIsraelTime } from '../../utils/israelTime'

export const IsraelClock: React.FC = () => {
  const [nowSec, setNowSec] = useState(() => Date.now() / 1000)

  useEffect(() => {
    const id = window.setInterval(() => {
      setNowSec(Date.now() / 1000)
    }, 1000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <span className="text-xs font-mono text-gray-500" title="שעון ישראל">
      {formatIsraelTime(nowSec, true)}
    </span>
  )
}
