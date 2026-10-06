import { contextBridge, ipcRenderer } from 'electron'

export type MenuCmd = 'settings' | 'tonight' | 'want' | 'watched' | 'profile' | 'film' | 'book' | 'music'

export interface PiankeApi {
  getInfo(): Promise<{ baseUrl: string; token: string; backendError: string | null }>
  openExternal(url: string): void
  reveal(path: string): void
  onMenu(cb: (cmd: MenuCmd) => void): () => void
  onFocus(cb: (focused: boolean) => void): () => void
  onBackendError(cb: (msg: string) => void): () => void
  /** true while the UI driver runs: skip long intro animations */
  driven: boolean
}

const api: PiankeApi = {
  getInfo: () => ipcRenderer.invoke('pianke:info'),
  openExternal: (url) => ipcRenderer.invoke('pianke:open-external', url),
  reveal: (p) => ipcRenderer.invoke('pianke:reveal', p),
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
}

contextBridge.exposeInMainWorld('pianke', api)
