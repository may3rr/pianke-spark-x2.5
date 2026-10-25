import { useEffect, useState } from 'react'

/** 演示模式: model names, timings and token counts for showing on-device
 *  running (competition demos). Off by default; everyday use doesn't need them. */
const KEY = 'pianke.demo'
const subs = new Set<(v: boolean) => void>()

export function demoOn(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function setDemo(v: boolean) {
  try {
    localStorage.setItem(KEY, v ? '1' : '0')
  } catch {
    /* per-viewer setting only */
  }
  subs.forEach((f) => f(v))
}

export function useDemo(): boolean {
  const [v, setV] = useState(demoOn)
  useEffect(() => {
    subs.add(setV)
    return () => {
      subs.delete(setV)
    }
  }, [])
  return v
}
