import type { ModelState, Status } from './api'

/** Usable now, or will load the moment it's asked for. */
export const modelUsable = (m: ModelState) => m.status === 'ready' || m.status === 'idle'

export function modelStatusLabel(m: ModelState): string {
  if (m.provider === 'api') return m.status === 'ready' ? m.host || '接口' : '未配置'
  return (
    {
      ready: '本机',
      idle: '用时加载',
      loading: '加载中',
      missing: '缺文件',
      error: '出错',
      stopped: '未启动',
    } as const
  )[m.status]
}

export const modelDot = (m: ModelState) =>
  m.status === 'ready' ? 'ready' : m.status === 'loading' ? 'loading' : m.status === 'idle' || m.status === 'stopped' ? '' : 'error'

/** The model that picks and writes, as the result footers name it. */
export const bigName = (s: Status) => s.models.find((m) => m.key === 'big')?.name ?? 'Spark-X2.5-4B'

// Screens deep in the tree (result footers, the log panel) name the model
// and say where the words go; App keeps this in step with /status rather
// than threading status through every component.
let current = { onDevice: true, host: '', big: 'Spark-X2.5-4B', small: 'Spark-X2.5-1.7B' }

export function syncModels(s: Status) {
  current = {
    onDevice: s.llm?.on_device ?? true,
    host: s.llm?.host ?? '',
    big: s.models.find((m) => m.key === 'big')?.name ?? current.big,
    small: s.models.find((m) => m.key === 'small')?.name ?? current.small,
  }
}

export const models = () => current
/** "Spark 1.7B" for the bundled models, the configured name otherwise */
export const shortName = (n: string) => n.replace('Spark-X2.5-', 'Spark ')
