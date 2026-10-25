import { useEffect, useState } from 'react'
import type { UpdateState } from '../../../preload/index'

export type { UpdateState }

/** The main process's update state, live. */
export function useUpdate(): UpdateState {
  const [s, setS] = useState<UpdateState>({ status: 'idle', current: '' })
  useEffect(() => {
    window.pianke.update.state().then(setS)
    return window.pianke.update.onState(setS)
  }, [])
  return s
}

/** Worth a blue dot: something to download, install, or fetch in full. */
export const hasUpdate = (s: UpdateState) => ['available', 'downloading', 'ready', 'full'].includes(s.status)

export const mb = (n?: number) => (n ? `${(n / 1e6).toFixed(n < 1e6 ? 2 : 1)} MB` : '')
