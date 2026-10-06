// Turn the built app into an update: one archive per part, latest.json, and
// the full dmg, in release/update/. With --publish, upload them as a GitHub
// release; installed apps find it through releases/latest/download/latest.json.
//
//   npm run dist                                   build 片刻.app and the dmg first
//   npm run release -- --notes "改了什么"            stage release/update/
//   npm run release -- --notes "改了什么" --publish  and upload it
//
// Bump "version" in package.json before `npm run dist`: the app only offers
// an update whose version is higher than its own.
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { COMPONENTS } from './components.mjs'

const REPO = 'may3rr/pianke-spark-x2.5'
const root = path.resolve(import.meta.dirname, '..')
const args = process.argv.slice(2)
const notes = args.includes('--notes') ? args[args.indexOf('--notes') + 1] : ''
const publish = args.includes('--publish')

const resources = path.join(root, 'release/mac-arm64/片刻.app/Contents/Resources')
const stamp = JSON.parse(fs.readFileSync(path.join(resources, 'components.json'), 'utf-8'))
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf-8'))
if (stamp.version !== pkg.version) {
  throw new Error(`built app is ${stamp.version}, package.json says ${pkg.version}: run npm run dist again`)
}
const dmgName = `片刻-${pkg.version}-arm64.dmg`
const dmg = path.join(root, 'release', dmgName)
if (!fs.existsSync(dmg)) throw new Error(`missing release/${dmgName}`)

const out = path.join(root, 'release/update')
fs.rmSync(out, { recursive: true, force: true })
fs.mkdirSync(out, { recursive: true })

const sha256 = (f) => createHash('sha256').update(fs.readFileSync(f)).digest('hex')
const components = {}
for (const [name, c] of Object.entries(COMPONENTS)) {
  const file = path.join(out, c.archive)
  if (name === 'app') {
    // read app.asar as bytes; gzip it whole
    fs.writeFileSync(file, zlib.gzipSync(fs.readFileSync(path.join(resources, c.path)), { level: 9 }))
  } else {
    // archives hold the folder by its Resources name; the updater untars beside them
    execFileSync('tar', ['--no-xattrs', '-czf', file, '-C', resources, c.path])
  }
  components[name] = {
    fingerprint: stamp.components[name],
    archive: c.archive,
    sha256: sha256(file),
    size: fs.statSync(file).size,
  }
}
fs.copyFileSync(dmg, path.join(out, dmgName))

const commit = execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root }).toString().trim()
const manifest = {
  version: pkg.version,
  electron: stamp.electron,
  notes,
  dmg: dmgName,
  commit,
  components,
}
fs.writeFileSync(path.join(out, 'latest.json'), JSON.stringify(manifest, null, 2) + '\n')

const mb = (n) => (n / 1e6).toFixed(2) + ' MB'
console.log(`release/update/ for ${pkg.version} (${commit}):`)
for (const [n, c] of Object.entries(components)) console.log(`  ${n.padEnd(12)} ${c.fingerprint}  ${mb(c.size)}`)

if (publish) {
  const files = fs.readdirSync(out).map((f) => path.join(out, f))
  execFileSync(
    'gh',
    ['release', 'create', `v${pkg.version}`, ...files, '--repo', REPO, '--title', `片刻 ${pkg.version}`,
      '--notes', `${notes || '更新'}\n\n构建自 ${commit}。已安装的片刻会在设置里提示更新，只下载有变化的部分。`],
    { stdio: 'inherit' }
  )
}
