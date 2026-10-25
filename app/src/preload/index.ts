import { contextBridge, ipcRenderer } from 'electron'

export type MenuCmd = 'settings' | 'tonight' | 'find' | 'want' | 'watched' | 'profile' | 'film' | 'book' | 'music'

export interface UpdateState {
  status: 'idle' | 'checking' | 'none' | 'available' | 'downloading' | 'ready' | 'full' | 'error'
  current: string
  version?: string
  notes?: string
  parts?: string[]
  size?: number
  received?: number
  error?: string
}

export interface PiankeApi {
  getInfo(): Promise<{ baseUrl: string; token: string; backendError: string | null }>
  openExternal(url: string): void
  reveal(path: string): void
  /** the renderer is sandboxed; the main process writes the clipboard */
  copy(text: string): Promise<void>
  onMenu(cb: (cmd: MenuCmd) => void): () => void
  onFocus(cb: (focused: boolean) => void): () => void
  onBackendError(cb: (msg: string | null) => void): () => void
  /** true while the UI driver runs: skip long intro animations */
  driven: boolean
  update: {
    state(): Promise<UpdateState>
    check(): Promise<UpdateState>
    download(): Promise<UpdateState>
    /** quits and reopens the app with the update in place */
    apply(): Promise<void>
    /** release page, for updates that need the full dmg */
    openPage(): Promise<void>
    onState(cb: (s: UpdateState) => void): () => void
  }
}

const api: PiankeApi = {
  getInfo: () => ipcRenderer.invoke('pianke:info'),
  openExternal: (url) => ipcRenderer.invoke('pianke:open-external', url),
  reveal: (p) => ipcRenderer.invoke('pianke:reveal', p),
  copy: (t) => ipcRenderer.invoke('pianke:copy', t),
  onMenu: (cb) => {
    const h = (_e: unknown, cmd: MenuCmd) => cb(cmd)
    ipcRenderer.on('pianke:menu', h)
    return () => ipcRenderer.off('pianke:menu', h)
  },
  onFocus: (cb) => {
    const h = (_e: unknown, f: boolean) => cb(f)
    ipcRenderer.on('pianke:focus', h)
    return () => ipcRenderer.off('pianke:focus', h)
  },
  onBackendError: (cb) => {
    const h = (_e: unknown, msg: string) => cb(msg)
    ipcRenderer.on('pianke:backend-error', h)
    return () => ipcRenderer.off('pianke:backend-error', h)
  },
  driven: !!process.env.PIANKE_DRIVE && process.env.PIANKE_DRIVE_FAST === '1',
  update: {
    state: () => ipcRenderer.invoke('pianke:update-state'),
    check: () => ipcRenderer.invoke('pianke:update-check'),
    download: () => ipcRenderer.invoke('pianke:update-download'),
    apply: () => ipcRenderer.invoke('pianke:update-apply'),
    openPage: () => ipcRenderer.invoke('pianke:update-page'),
    onState: (cb) => {
      const h = (_e: unknown, s: UpdateState) => cb(s)
      ipcRenderer.on('pianke:update', h)
      return () => ipcRenderer.off('pianke:update', h)
    },
  },
}

contextBridge.exposeInMainWorld('pianke', api)
