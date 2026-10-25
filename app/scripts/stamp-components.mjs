// Write Resources/components.json into the built app: its version, its
// Electron, and each part's fingerprint. The updater compares these with a
// release's latest.json to decide what to download.
import fs from 'node:fs'
import path from 'node:path'
import { fingerprints } from './components.mjs'

const root = path.resolve(import.meta.dirname, '..')
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf-8'))
const electron = JSON.parse(fs.readFileSync(path.join(root, 'node_modules/electron/package.json'), 'utf-8')).version
const resources = path.join(root, 'release/mac-arm64/片刻.app/Contents/Resources')
const runtimeKey = fs.readFileSync(path.join(root, 'build/backend/runtime.key'), 'utf-8').trim()

const stamp = { version: pkg.version, electron, components: fingerprints(resources, runtimeKey) }
fs.writeFileSync(path.join(resources, 'components.json'), JSON.stringify(stamp, null, 2) + '\n')
console.log('components:', JSON.stringify(stamp))
