import type { Title } from './api'

const KIND = { movie: '电影', series: '剧集', miniseries: '迷你剧', book: '书', album: '专辑' } as const

export function reltime(ts: number): string {
  const d = new Date(ts * 1000)
  const now = new Date()
  const day = 86400_000
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const hm = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  if (d.getTime() >= startToday) return `今天 ${hm}`
  if (d.getTime() >= startToday - day) return `昨天 ${hm}`
  if (d.getTime() >= startToday - 6 * day) return `星期${'日一二三四五六'[d.getDay()]} ${hm}`
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export function nightLabel(ts = Date.now() / 1000): string {
  const d = new Date(ts * 1000)
  const h = d.getHours()
  const part = h < 5 ? '深夜' : h < 11 ? '早上' : h < 14 ? '中午' : h < 18 ? '下午' : h < 23 ? '晚上' : '深夜'
  return `${d.getMonth() + 1}月${d.getDate()}日 星期${'日一二三四五六'[d.getDay()]} ${part}`
}

export function greeting(name: string): string {
  const h = new Date().getHours()
  const part = h < 5 ? '夜深了' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'
  return name ? `${part}，${name}` : part
}

export function yearSpan(t: Title): string {
  if (!t.year) return ''
  if (t.kind === 'movie') return String(t.year)
  return `${t.year}–${t.end_year ?? ''}`
}

export function metaLine(t: Title): string {
  if (t.domain === 'book' || t.domain === 'music') {
    return [(t.creators ?? []).slice(0, 2).join('、'), t.year ? String(t.year) : '', t.genres_zh.slice(0, 3).join('/')]
      .filter(Boolean)
      .join('，')
  }
  const bits = [yearSpan(t), KIND[t.kind] === '电影' ? '' : KIND[t.kind], t.genres_zh.slice(0, 3).join('/')]
  if (t.runtime) bits.push(`${t.runtime} 分钟`)
  return bits.filter(Boolean).join('，')
}

export function kindLabel(t: Title): string {
  return KIND[t.kind]
}

export function votes(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)} 万人评分`
  return `${n} 人评分`
}

export function doubanUrl(t: Title): string {
  return `https://search.douban.com/movie/subject_search?search_text=${encodeURIComponent(t.zh || t.title)}`
}

export function runtimeLabel(t: Title): string {
  if (!t.runtime) return '未知'
  const h = Math.floor(t.runtime / 60)
  const m = t.runtime % 60
  if (t.kind !== 'movie') return `每集约 ${t.runtime} 分钟`
  return h ? `${h} 小时${m ? ` ${m} 分钟` : ''}` : `${m} 分钟`
}
