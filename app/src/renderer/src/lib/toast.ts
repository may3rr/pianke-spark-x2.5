import { useEffect, useState } from 'react'

/** One toast at a time, bottom of the window. A removal shows "撤销" and
 *  only happens when the toast goes away: undo just never commits it. */
export interface ToastSpec {
  text: string
  /** runs when the toast leaves without 撤销 */
  commit?: () => void | Promise<void>
  /** runs on 撤销 */
  undo?: () => void
}

interface Live extends ToastSpec {
  id: number
}

const MS = 5000
let cur: Live | null = null
let timer: ReturnType<typeof setTimeout> | null = null
let seq = 0
const subs = new Set<(t: Live | null) => void>()
const emit = () => subs.forEach((f) => f(cur))

function settle(commit: boolean) {
  if (!cur) return
  const t = cur
  cur = null
  if (timer) clearTimeout(timer)
  timer = null
  emit()
  if (commit) void t.commit?.()
  else t.undo?.()
}

export function toast(spec: ToastSpec) {
  settle(true) // a new toast commits the one before it
  cur = { ...spec, id: ++seq }
  timer = setTimeout(() => settle(true), MS)
  emit()
}

export const undoToast = () => settle(false)
export const closeToast = () => settle(true)

// a pending removal still happens if the window closes
window.addEventListener('beforeunload', () => settle(true))

export function useToast(): Live | null {
  const [t, setT] = useState<Live | null>(cur)
  useEffect(() => {
    subs.add(setT)
    return () => {
      subs.delete(setT)
    }
  }, [])
  return t
}
