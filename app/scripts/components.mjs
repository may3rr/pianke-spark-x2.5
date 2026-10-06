// The parts of 片刻.app/Contents/Resources an update can replace on its own.
// Each gets a fingerprint; an update downloads only parts whose fingerprint
// changed. The Electron runtime itself is not one of them: a new Electron
// means downloading the full dmg.
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export const COMPONENTS = {
  // renderer + main process (~1.3 MB compressed)
  app: { path: 'app.asar', archive: 'app.asar.gz' },
  // the Python backend's own code, as source (~0.2 MB)
  'backend-src': { path: 'backend-src', archive: 'backend-src.tar.gz' },
  // frozen Python + third-party libraries (~19 MB); fingerprinted by
  // build/backend/runtime.key since PyInstaller output isn't reproducible
  runtime: { path: 'backend', archive: 'runtime.tar.gz' },
  // film catalog and book/album library (~17 MB)
  data: { path: 'data', archive: 'data.tar.gz' },
}

function walk(dir, rel = '') {
  return fs
    .readdirSync(path.join(dir, rel), { withFileTypes: true })
    .filter((e) => e.name !== '.DS_Store' && e.name !== '__pycache__')
    .sort((a, b) => (a.name < b.name ? -1 : 1))
    .flatMap((e) => (e.isDirectory() ? walk(dir, path.join(rel, e.name)) : [path.join(rel, e.name)]))
}

/** sha256 over relative paths and bytes, so a rebuild with the same files hashes the same */
export function contentHash(p) {
  const h = createHash('sha256')
  if (fs.statSync(p).isDirectory()) {
    for (const f of walk(p)) {
      h.update(f + '\0')
      h.update(fs.readFileSync(path.join(p, f)))
    }
  } else {
    h.update(fs.readFileSync(p))
  }
  return h.digest('hex').slice(0, 16)
}

/** Fingerprints of the parts inside a built app's Resources folder */
export function fingerprints(resources, runtimeKey) {
  // read app.asar as a plain file: under Electron, fs would open it as a folder
  return {
    app: contentHash(path.join(resources, COMPONENTS.app.path)),
    'backend-src': contentHash(path.join(resources, COMPONENTS['backend-src'].path)),
    runtime: runtimeKey,
    data: contentHash(path.join(resources, COMPONENTS.data.path)),
  }
}
