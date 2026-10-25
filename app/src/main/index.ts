import { app, BrowserWindow, clipboard, ipcMain, Menu, nativeTheme, shell } from 'electron'
import { spawn, ChildProcess, execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import net from 'node:net'
import path from 'node:path'
import fs from 'node:fs'
import { applyUpdate, checkForUpdate, downloadUpdate, openReleasePage, startUpdateChecks, updateState } from './updater'

// dev: a Python 3.11+ with the backend's dependencies and the repo's backend/.
// installed: the frozen backend and the catalogs in the bundle's Resources
// (see scripts/build-backend.sh). Either way the backend starts the two
// llama-server processes (Spark-X2.5 4B and 1.7B) on loopback ports.
const PYTHON = process.env.PIANKE_PYTHON || 'python3'
const BACKEND_DIR = path.resolve(import.meta.dirname, '../../../backend')
// where the backend keeps the user's data; models live here once installed
const PIANKE_HOME = process.env.PIANKE_HOME || path.join(app.getPath('appData'), 'Pianke')
const TOKEN = randomBytes(32).toString('hex')
const THEME = process.env.PIANKE_THEME
/** UI driver for screenshots and demo recording: a JSON list of steps */
const DRIVE = process.env.PIANKE_DRIVE
const SHOTS_DIR = process.env.PIANKE_SHOTS
/** demo recording: frames go to <dir>/frames.mkv, cursor and step log to <dir>/events.jsonl */
const REC_DIR = process.env.PIANKE_REC

let win: BrowserWindow | null = null
let backend: ChildProcess | null = null
let backendError: string | null = null
let port = 18740
let quitting = false
// crash-restart state: delay doubles per consecutive crash, resets after a minute up
let restartDelay = 1000
let backendStartedAt = 0

// ---------------------------------------------------------------- backend

function portFree(p: number): Promise<boolean> {
  return new Promise((resolve) => {
    const s = net.connect({ host: '127.0.0.1', port: p })
    s.once('connect', () => {
      s.destroy()
      resolve(false)
    })
    s.once('error', () => resolve(true))
  })
}

function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.listen(0, '127.0.0.1', () => {
      const a = srv.address()
      srv.close(() => resolve(typeof a === 'object' && a ? a.port : 18740))
    })
  })
}

async function startBackend(): Promise<void> {
  if (backend) return // a supervisor restart is already in flight
  if (!(await portFree(port))) port = await freePort()
  backendStartedAt = Date.now()
  if (app.isPackaged) {
    const res = process.resourcesPath
    fs.mkdirSync(PIANKE_HOME, { recursive: true })
    const log = fs.createWriteStream(path.join(PIANKE_HOME, 'backend.log'), { flags: 'w' })
    backend = spawn(path.join(res, 'backend', 'pianke-backend'), ['--port', String(port)], {
      env: {
        ...process.env,
        PIANKE_TOKEN: TOKEN,
        PIANKE_HOME,
        PIANKE_DATA: path.join(res, 'data'),
        // our Python code, as source beside the frozen runtime (updates swap it alone)
        PIANKE_SRC: path.join(res, 'backend-src'),
        PIANKE_MODELS: process.env.PIANKE_MODELS || path.join(PIANKE_HOME, 'models'),
      },
    })
    backend.stdout?.pipe(log)
    backend.stderr?.pipe(log)
  } else {
    backend = spawn(
      PYTHON,
      ['-m', 'uvicorn', 'pianke.server:app', '--host', '127.0.0.1', '--port', String(port)],
      {
        cwd: BACKEND_DIR,
        env: { ...process.env, PIANKE_TOKEN: TOKEN },
      }
    )
    backend.stdout?.on('data', (d) => process.stdout.write(`[backend] ${d}`))
    backend.stderr?.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  }
  backend.on('error', (e) => {
    backend = null
    if (!quitting) scheduleBackendRestart(`后端启动失败：${e.message}`)
  })
  backend.on('exit', (code) => {
    const wasUp = Date.now() - backendStartedAt
    if (wasUp > 60_000) restartDelay = 1000 // it was stable; start counting again
    backend = null
    if (!quitting) {
      scheduleBackendRestart(code ? `后端退出了（退出码 ${code}）` : '后端意外退出')
    } else if (code && code !== 0 && !backendError) {
      backendError = `退出码 ${code}`
    }
  })
}

/** Restart the backend after a crash, with backoff; tell the renderer when
 *  it is healthy again so the error screen can let go. */
function scheduleBackendRestart(reason: string): void {
  backendError = `${reason}，${Math.round(restartDelay / 1000)} 秒后自动重启`
  win?.webContents.send('pianke:backend-error', backendError)
  const wait = restartDelay
  restartDelay = Math.min(restartDelay * 2, 30_000)
  setTimeout(() => {
    if (quitting || backend) return
    startBackend().then(async () => {
      const deadline = Date.now() + 30_000
      while (Date.now() < deadline && !quitting) {
        if (!(await portFree(port))) break // someone is listening again
        await new Promise((r) => setTimeout(r, 400))
      }
      if (!quitting) {
        backendError = null
        win?.webContents.send('pianke:backend-error', null)
      }
    })
  }, wait)
}

let stopping: Promise<void> | null = null

/** Stop the backend for good (quit or update); resolves once it has exited.
 *  It stops the llama-servers one after another, up to 5 s each, so give it
 *  room before the SIGKILL. */
function killBackend(): Promise<void> {
  quitting = true // no supervisor restart from here on
  if (stopping) return stopping
  const b = backend
  backend = null
  if (!b || b.exitCode !== null || b.signalCode !== null) return Promise.resolve()
  stopping = new Promise((resolve) => {
    const force = setTimeout(() => b.kill('SIGKILL'), 12_000)
    b.once('exit', () => {
      clearTimeout(force)
      resolve()
    })
  })
  b.kill('SIGTERM')
  return stopping
}

// ---------------------------------------------------------------- ipc

ipcMain.handle('pianke:info', () => ({
  baseUrl: `http://127.0.0.1:${port}`,
  token: TOKEN,
  backendError,
}))

ipcMain.handle('pianke:open-external', (_e, url: string) => {
  if (typeof url === 'string' && url.startsWith('https://')) shell.openExternal(url)
})

ipcMain.handle('pianke:reveal', (_e, p: string) => {
  shell.showItemInFolder(p)
})

ipcMain.handle('pianke:copy', (_e, text: string) => {
  if (typeof text === 'string') clipboard.writeText(text)
})

ipcMain.handle('pianke:update-state', () => updateState())
ipcMain.handle('pianke:update-check', () => checkForUpdate())
ipcMain.handle('pianke:update-download', () => downloadUpdate())
ipcMain.handle('pianke:update-apply', () => applyUpdate(killBackend))
ipcMain.handle('pianke:update-page', () => openReleasePage())

// ---------------------------------------------------------------- driver

type Step =
  | { wait: string; timeout?: number }
  | { click: string; text?: string }
  | { type: [string, string] }
  | { key: string }
  | { shot: string }
  | { sleep: number }
  | { theme: 'light' | 'dark' }
  | { eval: string }
  | { rec: 'start' | 'stop' }
  | { mark: string }
  | { move: string }
  | { park: [number, number] }
  | { drag: [string, number, number] }
  | { scroll: [string, string] }
  | { imgs: number }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function js<T = unknown>(code: string): Promise<T> {
  return win!.webContents.executeJavaScript(code, true) as Promise<T>
}

async function capture(name: string) {
  if (!SHOTS_DIR || !win) return
  fs.mkdirSync(SHOTS_DIR, { recursive: true })
  const file = path.join(SHOTS_DIR, `${name}.png`)
  const wid = win.getMediaSourceId().split(':')[1]
  const ok = await new Promise<boolean>((resolve) =>
    execFile('/usr/sbin/screencapture', ['-x', '-o', `-l${wid}`, file], (err) =>
      resolve(!err && fs.existsSync(file) && fs.statSync(file).size > 10000)
    )
  )
  if (!ok) {
    const img = await win.webContents.capturePage()
    fs.writeFileSync(file, img.toPNG())
  }
  console.log(`SHOT ${file}`)
}

// ---------------------------------------------------------------- recorder

const rec = {
  on: false,
  t0: 0,
  ff: null as ChildProcess | null,
  log: null as fs.WriteStream | null,
  latest: null as Buffer | null,
  size: [0, 0] as [number, number],
  timer: null as NodeJS.Timeout | null,
  frames: 0,
  dropped: 0,
  backed: false,
}
const mouse = { x: 640, y: 410 }

function recLog(ev: Record<string, unknown>) {
  if (!rec.on) return
  rec.log!.write(JSON.stringify({ t: Date.now() - rec.t0, ...ev }) + '\n')
}

function recStart() {
  if (!REC_DIR || rec.on) return
  fs.mkdirSync(REC_DIR, { recursive: true })
  rec.log = fs.createWriteStream(path.join(REC_DIR, 'events.jsonl'))
  rec.on = true
  rec.t0 = Date.now()
  recLog({ type: 'start' })
  recLog({ type: 'cursor', x: mouse.x, y: mouse.y, cur: 'arrow' })
  win!.webContents.beginFrameSubscription(false, (image) => {
    const { width, height } = image.getSize()
    if (!rec.ff) {
      rec.size = [width, height]
      recLog({ type: 'size', w: width, h: height })
      rec.ff = spawn('ffmpeg', [
        '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', `${width}x${height}`, '-r', '30', '-i', '-',
        '-c:v', 'ffv1', '-level', '3', '-slices', '24', '-threads', '8', '-pix_fmt', 'bgra',
        path.join(REC_DIR!, 'frames.mkv'),
      ], { stdio: ['pipe', 'inherit', 'inherit'] })
      rec.ff.stdin!.on('drain', () => (rec.backed = false))
    }
    // a resize mid-recording would corrupt the raw stream; keep the first size
    if (width === rec.size[0] && height === rec.size[1]) rec.latest = image.toBitmap()
  })
  rec.timer = setInterval(() => {
    if (!rec.latest || !rec.ff) return
    if (rec.backed) {
      rec.dropped++
      return
    }
    // frame i of frames.mkv was taken at time t: the compositor maps time to frames
    recLog({ type: 'frame', i: rec.frames++ })
    rec.backed = !rec.ff.stdin!.write(rec.latest)
  }, 1000 / 30)
}

async function recStop() {
  if (!rec.on) return
  clearInterval(rec.timer!)
  win!.webContents.endFrameSubscription()
  recLog({ type: 'stop', frames: rec.frames, dropped: rec.dropped })
  rec.on = false
  await new Promise<void>((r) => rec.log!.end(r))
  if (rec.ff) {
    const done = new Promise((r) => rec.ff!.once('exit', r))
    rec.ff.stdin!.end()
    await done
  }
  console.log(`REC_DONE frames=${rec.frames} dropped=${rec.dropped}`)
}

const ease = (k: number) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2)

async function cursorAt(x: number, y: number): Promise<string> {
  return js<string>(`(() => {
    const el = document.elementFromPoint(${x}, ${y});
    if (!el) return 'arrow';
    const c = getComputedStyle(el).cursor;
    if (c === 'pointer') return 'pointer';
    if (c === 'text' || el.closest('textarea, input:not([type=range])')) return 'text';
    return 'arrow';
  })()`)
}

/** glide the pointer with real mouseMove events so hover states render */
async function glide(x: number, y: number) {
  const fx = mouse.x
  const fy = mouse.y
  const dist = Math.hypot(x - fx, y - fy)
  const ms = Math.min(1100, Math.max(420, 300 + dist * 0.75))
  // slight arc: offset the midpoint perpendicular to the path
  const bend = Math.min(60, dist * 0.12) * (fx < x ? -1 : 1)
  const nx = dist ? -(y - fy) / dist : 0
  const ny = dist ? (x - fx) / dist : 0
  const t0 = Date.now()
  let cur = 'arrow'
  for (;;) {
    const k = Math.min(1, (Date.now() - t0) / ms)
    const e = ease(k)
    const arc = Math.sin(Math.PI * e) * bend
    mouse.x = fx + (x - fx) * e + nx * arc
    mouse.y = fy + (y - fy) * e + ny * arc
    win!.webContents.sendInputEvent({ type: 'mouseMove', x: Math.round(mouse.x), y: Math.round(mouse.y) })
    if (k > 0.6 && k < 0.7) cur = await cursorAt(Math.round(x), Math.round(y))
    recLog({ type: 'cursor', x: mouse.x, y: mouse.y, cur: k < 0.65 ? 'arrow' : cur })
    if (k >= 1) break
    await sleep(16)
  }
  cur = await cursorAt(Math.round(x), Math.round(y))
  recLog({ type: 'cursor', x: mouse.x, y: mouse.y, cur })
}

/** centre of an element, scrolled into view first if it is off screen */
async function target(sel: string): Promise<[number, number] | null> {
  const q = `(() => {
    const el = document.querySelector(${JSON.stringify(sel)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [r.left + r.width / 2, r.top + r.height / 2, r.top, r.bottom, innerHeight];
  })()`
  let r = await js<number[] | null>(q)
  if (!r) return null
  if (r[2] < 0 || r[3] > r[4]) {
    await js(`document.querySelector(${JSON.stringify(sel)}).scrollIntoView({ block: 'center', behavior: 'smooth' })`)
    await sleep(700)
    r = await js<number[] | null>(q)
    if (!r) return null
  }
  return [r[0], r[1]]
}

async function press(down: boolean, count = 1) {
  const x = Math.round(mouse.x)
  const y = Math.round(mouse.y)
  win!.webContents.sendInputEvent({ type: down ? 'mouseDown' : 'mouseUp', x, y, button: 'left', clickCount: count })
  recLog({ type: down ? 'down' : 'up', x: mouse.x, y: mouse.y })
}

async function realClick(sel: string) {
  const p = await target(sel)
  if (!p) return
  await glide(p[0], p[1])
  await sleep(120)
  await press(true)
  await sleep(70)
  await press(false)
  await sleep(160)
}

async function realType(sel: string, text: string) {
  const focused = await js<boolean>(`document.activeElement === document.querySelector(${JSON.stringify(sel)})`)
  if (!focused) await realClick(sel)
  await js(`document.querySelector(${JSON.stringify(sel)})?.focus()`)
  recLog({ type: 'typing', on: true })
  const chars = [...text]
  for (let i = 0; i < chars.length; ) {
    // an IME commits Chinese a word or two at a time; Latin goes per key
    const n = /[\u4e00-\u9fff]/.test(chars[i]) ? 1 + Math.floor(Math.random() * 2) : 1
    win!.webContents.insertText(chars.slice(i, i + n).join(''))
    i += n
    const ch = chars[i - 1]
    await sleep(/[，。、！？,.]/.test(ch) ? 260 : 70 + Math.random() * 60)
  }
  recLog({ type: 'typing', on: false })
}

async function drive(file: string) {
  const steps: Step[] = JSON.parse(fs.readFileSync(file, 'utf-8'))
  for (const s of steps) {
    if ('wait' in s) {
      const deadline = Date.now() + (s.timeout ?? 120_000)
      let found = false
      while (Date.now() < deadline) {
        if (await js<boolean>(`!!document.querySelector(${JSON.stringify(s.wait)})`)) {
          found = true
          break
        }
        await sleep(250)
      }
      if (!found) {
        await capture('timeout')
        throw new Error(`WAIT_TIMEOUT ${s.wait}`)
      }
      // long waits (model work) are sped up in the edit; it needs their span
      recLog({ type: 'wait', sel: s.wait, a: deadline - (s.timeout ?? 120_000) - rec.t0 })
    } else if ('click' in s) {
      let sel = s.click
      if (s.text) {
        // the first match whose text contains s.text, e.g. a wall tile by title
        await js(`(() => {
          document.querySelectorAll('[data-drive-hit]').forEach((e) => e.removeAttribute('data-drive-hit'));
          [...document.querySelectorAll(${JSON.stringify(s.click)})]
            .find((e) => e.textContent.includes(${JSON.stringify(s.text)}))
            ?.setAttribute('data-drive-hit', '');
        })()`)
        sel = '[data-drive-hit]'
      }
      if (rec.on) await realClick(sel)
      else await js(`document.querySelector(${JSON.stringify(sel)})?.click()`)
    } else if ('type' in s && rec.on) {
      await realType(s.type[0], s.type[1])
    } else if ('type' in s) {
      const [sel, text] = s.type
      // React-controlled inputs need the native setter + an input event
      await js(`(() => {
        const el = document.querySelector(${JSON.stringify(sel)});
        if (!el) return;
        el.focus();
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(text)});
        el.dispatchEvent(new Event('input', { bubbles: true }));
      })()`)
    } else if ('key' in s) {
      win!.webContents.sendInputEvent({ type: 'keyDown', keyCode: s.key })
      win!.webContents.sendInputEvent({ type: 'keyUp', keyCode: s.key })
    } else if ('shot' in s) {
      await capture(s.shot)
    } else if ('sleep' in s) {
      await sleep(s.sleep)
    } else if ('theme' in s) {
      nativeTheme.themeSource = s.theme
      await sleep(400)
    } else if ('eval' in s) {
      await js(s.eval)
    } else if ('rec' in s) {
      if (s.rec === 'start') recStart()
      else await recStop()
    } else if ('mark' in s) {
      recLog({ type: 'mark', id: s.mark })
    } else if ('move' in s) {
      const p = await target(s.move)
      if (p) await glide(p[0], p[1])
    } else if ('park' in s) {
      await glide(s.park[0], s.park[1])
    } else if ('drag' in s) {
      // drag across an element from one horizontal fraction to another
      const [sel, a, b] = s.drag
      const r = await js<number[] | null>(`(() => {
        const r = document.querySelector(${JSON.stringify(sel)})?.getBoundingClientRect();
        return r ? [r.left, r.top, r.width, r.height] : null;
      })()`)
      if (r) {
        const y = r[1] + r[3] / 2
        await glide(r[0] + r[2] * a, y)
        await sleep(100)
        await press(true)
        const steps = 28
        for (let i = 1; i <= steps; i++) {
          mouse.x = r[0] + r[2] * (a + ((b - a) * ease(i / steps)))
          win!.webContents.sendInputEvent({ type: 'mouseMove', x: Math.round(mouse.x), y: Math.round(y), button: 'left', modifiers: ['leftbuttondown'] })
          recLog({ type: 'cursor', x: mouse.x, y, cur: 'pointer' })
          await sleep(22)
        }
        await sleep(80)
        await press(false)
      }
    } else if ('imgs' in s) {
      // let the covers on screen finish loading (or fail to the typographic one)
      const deadline = Date.now() + s.imgs
      while (Date.now() < deadline) {
        const pending = await js<number>(`[...document.querySelectorAll('.cover img')].filter((im) => {
          const r = im.getBoundingClientRect();
          return r.bottom > 0 && r.top < innerHeight && !(im.complete && im.naturalWidth > 0);
        }).length`)
        if (!pending) break
        await sleep(250)
      }
      recLog({ type: 'wait', sel: 'imgs', a: deadline - s.imgs - rec.t0 })
    } else if ('scroll' in s) {
      const [sel, to] = s.scroll
      await js(`(() => {
        const box = document.querySelector('.main-area');
        const el = document.querySelector(${JSON.stringify(sel)});
        if (!box) return;
        if (el && el !== box) el.scrollIntoView({ block: ${JSON.stringify(to)}, behavior: 'smooth' });
        else box.scrollTo({ top: ${JSON.stringify(to)} === 'end' ? 1e6 : 0, behavior: 'smooth' });
      })()`)
      await sleep(900)
    }
  }
  await recStop()
  console.log('DRIVE_DONE')
  if (process.env.PIANKE_DRIVE_QUIT !== '0') app.quit()
}

// ---------------------------------------------------------------- menu

function menuClick(cmd: string) {
  return () => win?.webContents.send('pianke:menu', cmd)
}

function buildMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: app.name,
      submenu: [
        { role: 'about', label: `关于${app.name}` },
        { type: 'separator' },
        { label: '设置…', accelerator: 'CmdOrCtrl+,', click: menuClick('settings') },
        { type: 'separator' },
        { role: 'hide', label: `隐藏${app.name}` },
        { role: 'hideOthers', label: '隐藏其他' },
        { role: 'unhide', label: '全部显示' },
        { type: 'separator' },
        { role: 'quit', label: `退出${app.name}` },
      ],
    },
    {
      label: '片刻',
      submenu: [
        { label: '今晚看什么', accelerator: 'CmdOrCtrl+N', click: menuClick('tonight') },
        { label: '找作品…', accelerator: 'CmdOrCtrl+K', click: menuClick('find') },
        { type: 'separator' },
        { label: '影视', accelerator: 'CmdOrCtrl+1', click: menuClick('film') },
        { label: '书', accelerator: 'CmdOrCtrl+2', click: menuClick('book') },
        { label: '音乐', accelerator: 'CmdOrCtrl+3', click: menuClick('music') },
        { label: '口味画像', accelerator: 'CmdOrCtrl+4', click: menuClick('profile') },
      ],
    },
    { label: '编辑', role: 'editMenu' },
    { label: '显示', role: 'viewMenu' },
    { label: '窗口', role: 'windowMenu' },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ---------------------------------------------------------------- window

async function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1040,
    minHeight: 700,
    show: false,
    title: '片刻',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 20, y: 20 },
    vibrancy: 'sidebar',
    visualEffectState: 'followWindow',
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(import.meta.dirname, '../preload/index.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
    },
  })
  if (THEME === 'light' || THEME === 'dark') nativeTheme.themeSource = THEME
  if (DRIVE) {
    win.webContents.on('console-message', (_e, _l, msg) => console.log(`[renderer] ${msg}`))
  }
  // Electron has no right-click menu of its own: copy on a selection, the
  // usual edit commands in a text box
  win.webContents.on('context-menu', (_e, p) => {
    const items: Electron.MenuItemConstructorOptions[] = p.isEditable
      ? [
          { role: 'cut', label: '剪切', enabled: p.editFlags.canCut },
          { role: 'copy', label: '拷贝', enabled: p.editFlags.canCopy },
          { role: 'paste', label: '粘贴', enabled: p.editFlags.canPaste },
          { type: 'separator' },
          { role: 'selectAll', label: '全选' },
        ]
      : p.selectionText.trim()
        ? [{ role: 'copy', label: '拷贝' }]
        : []
    if (items.length) Menu.buildFromTemplate(items).popup({ window: win! })
  })
  win.on('focus', () => win?.webContents.send('pianke:focus', true))
  // a recording keeps the focused look even when another app is in front
  if (!REC_DIR) win.on('blur', () => win?.webContents.send('pianke:focus', false))
  win.once('ready-to-show', () => {
    win?.show()
    if (DRIVE) setTimeout(() => drive(DRIVE).catch((e) => {
      console.error('DRIVE_ERROR', e)
      app.quit()
    }), 400)
  })
  const devUrl = process.env.ELECTRON_RENDERER_URL
  if (devUrl) await win.loadURL(devUrl)
  else await win.loadFile(path.join(import.meta.dirname, '../renderer/index.html'))
}

app.setName('片刻')

app.whenReady().then(async () => {
  buildMenu()
  await startBackend()
  await createWindow()
  if (!DRIVE || process.env.PIANKE_UPDATE_URL) startUpdateChecks()
})

app.on('window-all-closed', () => app.quit())
// hold the quit until the backend (and its llama-servers) are down: otherwise
// the SIGKILL fallback dies with us, and an update's swap script (which waits
// on our pid) would replace files under a backend that is still running
let backendDown = false
app.on('before-quit', (e) => {
  if (backendDown) return
  e.preventDefault()
  for (const w of BrowserWindow.getAllWindows()) w.hide()
  killBackend().then(() => {
    backendDown = true
    app.quit()
  })
})
process.on('exit', () => backend?.kill('SIGKILL'))
