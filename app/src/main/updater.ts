/**
 * Incremental updates from GitHub Releases, without code signing.
 *
 * Each release carries latest.json (version, Electron version, a fingerprint
 * and archive per part, see scripts/components.mjs) plus the archives. The
 * app compares those fingerprints with its own Resources/components.json and
 * downloads only the parts that changed — usually the 1–2 MB of code. After
 * the app quits, a small shell script swaps the parts inside the bundle and
 * reopens it. A release with a different Electron needs the full dmg.
 *
 * Squirrel/electron-updater is not used: on macOS it requires a signed app.
 */
import { app, BrowserWindow, net, shell } from 'electron'
import { execFile, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'
import { createGunzip } from 'node:zlib'
import { pipeline } from 'node:stream/promises'

const run = promisify(execFile)

const FEED =
  process.env.PIANKE_UPDATE_URL ||
  'https://github.com/may3rr/pianke-spark-x2.5/releases/latest/download/latest.json'
const RELEASES = 'https://github.com/may3rr/pianke-spark-x2.5/releases/latest'
const EVERY = 6 * 3600_000

type Part = 'app' | 'backend-src' | 'runtime' | 'data'
// where each part lives in Resources, and the staged name the swap script moves
// in (app.asar is staged under another name: Electron's fs treats *.asar as a folder)
const PLACE: Record<Part, { dest: string; staged: string }> = {
  app: { dest: 'app.asar', staged: 'app-asar.bin' },
  'backend-src': { dest: 'backend-src', staged: 'backend-src' },
  runtime: { dest: 'backend', staged: 'backend' },
  data: { dest: 'data', staged: 'data' },
}

interface Manifest {
  version: string
  electron: string
  notes?: string
  dmg?: string
  components: Record<Part, { fingerprint: string; archive: string; sha256: string; size: number }>
}

export interface UpdateState {
  status: 'idle' | 'checking' | 'none' | 'available' | 'downloading' | 'ready' | 'full' | 'error'
  current: string
  version?: string
  notes?: string
  /** parts to download and their total size */
  parts?: Part[]
  size?: number
  received?: number
  error?: string
}

let state: UpdateState = { status: 'idle', current: app.getVersion() }
let manifest: Manifest | null = null
let manifestUrl = FEED
const staging = () =>
  path.join(process.env.PIANKE_HOME || path.join(app.getPath('appData'), 'Pianke'), 'updates')

function set(s: Partial<UpdateState>) {
  state = { ...state, ...s }
  for (const w of BrowserWindow.getAllWindows()) w.webContents.send('pianke:update', state)
}

export const updateState = () => state

function local(): { version: string; components: Record<Part, string> } | null {
  try {
    return JSON.parse(fs.readFileSync(path.join(process.resourcesPath, 'components.json'), 'utf-8'))
  } catch {
    return null
  }
}

const newer = (a: string, b: string) => {
  const x = a.split('.').map(Number)
  const y = b.split('.').map(Number)
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0)
  return false
}

export async function checkForUpdate(): Promise<UpdateState> {
  const mine = local()
  // development runs and builds without components.json have nothing to update
  if (!app.isPackaged || !mine) return state
  if (state.status === 'downloading' || state.status === 'ready') return state
  set({ status: 'checking', error: undefined })
  try {
    const r = await net.fetch(FEED, { cache: 'no-store' })
    if (!r.ok) throw new Error(`读取版本信息失败（${r.status}）`)
    manifestUrl = r.url || FEED // after GitHub's redirect to the release
    manifest = (await r.json()) as Manifest
    if (!newer(manifest.version, mine.version)) {
      set({ status: 'none', version: manifest.version })
      return state
    }
    const info = { version: manifest.version, notes: manifest.notes }
    if (manifest.electron !== process.versions.electron || !writable()) {
      set({ status: 'full', ...info })
      return state
    }
    const parts = (Object.keys(PLACE) as Part[]).filter(
      (p) => manifest!.components[p]?.fingerprint !== mine.components[p]
    )
    const size = parts.reduce((n, p) => n + manifest!.components[p].size, 0)
    set({ status: 'available', ...info, parts, size, received: 0 })
  } catch (e) {
    set({ status: 'error', error: (e as Error).message })
  }
  return state
}

/** The bundle must be writable to swap parts in place (true when the user dragged it to /Applications). */
function writable(): boolean {
  try {
    fs.accessSync(process.resourcesPath, fs.constants.W_OK)
    return true
  } catch {
    return false
  }
}

export async function downloadUpdate(): Promise<UpdateState> {
  if (state.status !== 'available' || !manifest) return state
  const dir = path.join(staging(), manifest.version)
  fs.rmSync(dir, { recursive: true, force: true })
  fs.mkdirSync(dir, { recursive: true })
  set({ status: 'downloading', received: 0 })
  try {
    let received = 0
    for (const part of state.parts ?? []) {
      const c = manifest.components[part]
      const url = new URL(c.archive, manifestUrl).toString()
      const r = await net.fetch(url)
      if (!r.ok || !r.body) throw new Error(`下载 ${c.archive} 失败（${r.status}）`)
      const file = path.join(dir, c.archive)
      const out = fs.createWriteStream(file)
      const hash = createHash('sha256')
      const reader = r.body.getReader()
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        hash.update(value)
        out.write(value)
        received += value.length
        set({ received })
      }
      await new Promise<void>((res, rej) => out.end((e?: Error | null) => (e ? rej(e) : res())))
      if (hash.digest('hex') !== c.sha256) throw new Error(`${c.archive} 校验不通过，可能没下完整`)
      if (part === 'app') {
        await pipeline(fs.createReadStream(file), createGunzip(), fs.createWriteStream(path.join(dir, PLACE.app.staged)))
      } else {
        await run('tar', ['-xzf', file, '-C', dir])
      }
      fs.rmSync(file)
    }
    fs.writeFileSync(path.join(dir, 'components.json'), JSON.stringify({
      version: manifest.version,
      electron: manifest.electron,
      components: Object.fromEntries(
        (Object.keys(PLACE) as Part[]).map((p) => [p, manifest!.components[p].fingerprint])
      ),
    }, null, 2))
    set({ status: 'ready' })
  } catch (e) {
    fs.rmSync(dir, { recursive: true, force: true })
    set({ status: 'error', error: (e as Error).message })
  }
  return state
}

/** Quit, let a detached script swap the staged parts in, reopen the app. */
export function applyUpdate(beforeQuit: () => void): void {
  if (state.status !== 'ready' || !manifest) return
  const dir = path.join(staging(), manifest.version)
  const res = process.resourcesPath
  const bundle = path.resolve(res, '../..')
  const q = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`
  const lines = [
    '#!/bin/sh',
    `while kill -0 ${process.pid} 2>/dev/null; do sleep 0.2; done`,
    ...(state.parts ?? []).flatMap((p) => [
      `rm -rf ${q(path.join(res, PLACE[p].dest))}`,
      `mv ${q(path.join(dir, PLACE[p].staged))} ${q(path.join(res, PLACE[p].dest))}`,
    ]),
    `mv ${q(path.join(dir, 'components.json'))} ${q(path.join(res, 'components.json'))}`,
    // Finder's "Get Info" reads the version from Info.plist
    `/usr/libexec/PlistBuddy -c ${q(`Set :CFBundleShortVersionString ${manifest.version}`)} ${q(path.join(bundle, 'Contents/Info.plist'))} 2>/dev/null`,
    `rm -rf ${q(staging())}`,
    // tests set PIANKE_UPDATE_NO_REOPEN so the swapped app isn't launched with real data
    ...(process.env.PIANKE_UPDATE_NO_REOPEN ? [] : [`open ${q(bundle)}`]),
  ]
  const script = path.join(staging(), 'apply.sh')
  fs.writeFileSync(script, lines.join('\n') + '\n', { mode: 0o755 })
  spawn('/bin/sh', [script], { detached: true, stdio: 'ignore' }).unref()
  beforeQuit()
  app.quit()
}

export function openReleasePage(): void {
  shell.openExternal(RELEASES)
}

export function startUpdateChecks(): void {
  if (!app.isPackaged) return
  setTimeout(checkForUpdate, 8_000)
  setInterval(checkForUpdate, EVERY)
}

