// Render scripts/icon.svg to build/icon.icns with transparency:
//   npx electron scripts/make-icon.mjs
// (Electron's offscreen renderer keeps the alpha channel that qlmanage drops.)
import { app, BrowserWindow } from 'electron'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const svg = fs.readFileSync(path.join(root, 'scripts/icon.svg'), 'utf-8')
const set = path.join(root, 'build/icon.iconset')

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 1024, height: 1024, show: false, transparent: true, frame: false,
    webPreferences: { offscreen: true },
  })
  win.webContents.setZoomFactor(1)
  await win.loadURL(
    'data:text/html,' + encodeURIComponent(
      `<html><body style="margin:0;background:transparent">${svg}</body></html>`
    )
  )
  await new Promise((r) => setTimeout(r, 300))
  const png = (await win.webContents.capturePage({ x: 0, y: 0, width: 1024, height: 1024 })).resize({ width: 1024, height: 1024 })
  fs.rmSync(set, { recursive: true, force: true })
  fs.mkdirSync(set, { recursive: true })
  for (const s of [16, 32, 128, 256, 512]) {
    fs.writeFileSync(path.join(set, `icon_${s}x${s}.png`), png.resize({ width: s, height: s, quality: 'best' }).toPNG())
    fs.writeFileSync(path.join(set, `icon_${s}x${s}@2x.png`), png.resize({ width: s * 2, height: s * 2, quality: 'best' }).toPNG())
  }
  fs.writeFileSync(path.join(root, 'build/icon.png'), png.toPNG())
  execFileSync('iconutil', ['-c', 'icns', set, '-o', path.join(root, 'build/icon.icns')])
  fs.rmSync(set, { recursive: true, force: true })
  console.log('build/icon.icns')
  app.quit()
})
