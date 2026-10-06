import type { Domain, Title } from './api'

/** Everything the UI says differently per shelf. Mirrors backend domains.py. */
export interface DomainCopy {
  key: Domain
  label: string
  unit: string
  noun: string
  verb: string
  done: string
  finished: string
  dropped: string
  list: string
  ask: string
  pickTitle: string
  pick3: string
  composeHint: string
  placeholder: string
  verifyStep: string
  color: string
  aspect: number // cover width / height
  chips: { key: string; options: string[] }[]
}

export const DOMAINS: Record<Domain, DomainCopy> = {
  film: {
    key: 'film',
    label: '影视',
    unit: '部',
    noun: '片',
    verb: '看',
    done: '看过',
    finished: '看完了',
    dropped: '没看完',
    list: '片单',
    ask: '今晚看什么',
    pickTitle: '今晚的三部',
    pick3: '挑三部',
    composeHint: '说说今天的状态，片刻只挑三部。',
    placeholder: '比如：今天加班到很晚，想看点暖一点、不用动脑的',
    verifyStep: '在片库里核实',
    color: 'var(--tile-indigo)',
    aspect: 2 / 3,
    chips: [
      { key: '时长', options: ['一个半小时内', '两小时以内', '不限', '来部剧'] },
      { key: '状态', options: ['累了', '想笑', '想哭一场', '想动动脑', '心情不好'] },
      { key: '和谁', options: ['一个人', '和伴侣', '和朋友', '和家人'] },
    ],
  },
  book: {
    key: 'book',
    label: '书',
    unit: '本',
    noun: '书',
    verb: '读',
    done: '读过',
    finished: '读完了',
    dropped: '没读完',
    list: '书单',
    ask: '下一本读什么',
    pickTitle: '接下来读的三本',
    pick3: '挑三本',
    composeHint: '说说最近的状态和想读的感觉，片刻只挑三本。',
    placeholder: '比如：最近通勤时间长，想读点短一些、能一口气读完的小说',
    verifyStep: '在书库和网上核实书名',
    color: 'var(--tile-teal)',
    aspect: 0.7,
    chips: [
      { key: '篇幅', options: ['薄一点', '中等', '大部头也行'] },
      { key: '状态', options: ['想放松', '想被打动', '想动动脑', '想逃离现实'] },
      { key: '场景', options: ['通勤路上', '睡前', '周末整块时间', '旅行'] },
    ],
  },
  music: {
    key: 'music',
    label: '音乐',
    unit: '张',
    noun: '专辑',
    verb: '听',
    done: '听过',
    finished: '听完了',
    dropped: '没听完',
    list: '歌单',
    ask: '现在听什么',
    pickTitle: '现在听的三张',
    pick3: '挑三张',
    composeHint: '说说你在做什么、什么心情，片刻只挑三张专辑。',
    placeholder: '比如：下午要写报告，想要不抢注意力、没什么人声的',
    verifyStep: '在曲库和网上核实专辑',
    color: 'var(--tile-pink)',
    aspect: 1,
    chips: [
      { key: '场景', options: ['工作专注', '通勤', '运动', '睡前', '做饭'] },
      { key: '心情', options: ['想安静', '想燃一点', '有点丧', '很开心'] },
      { key: '新鲜度', options: ['熟悉的风格', '来点新鲜的'] },
    ],
  },
}

export const DOMAIN_ORDER: Domain[] = ['film', 'book', 'music']

export function domainOf(id: string): Domain {
  return id.startsWith('bk:') ? 'book' : id.startsWith('mu:') ? 'music' : 'film'
}

export function creatorLine(t: Title): string {
  if (t.domain === 'film') return (t.directors ?? []).slice(0, 2).join('、')
  return (t.creators ?? []).slice(0, 2).join('、')
}
