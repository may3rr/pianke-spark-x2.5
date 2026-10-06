import { useEffect, useState } from 'react'
import { get, post, put, type Status } from '../lib/api'
import { BooksFillIcon, CpuFillIcon, GearFillIcon, LockFillIcon, Tile, WifiSlashFillIcon } from '../components/Icons'

interface Usage {
  by_model: { model: string; calls: number; prompt_tokens: number; completion_tokens: number; seconds: number; avg_gen_tps: number; avg_prompt_tps: number }[]
  bench: null | {
    model: string
    machine: string
    rows: { ctx: number; prompt_tps: number; first_seconds: number; cached_seconds: number; gen_tps: number }[]
  }
  big_ctx: number
}

const gb = (b: number | null) => (b ? `${(b / 1e9).toFixed(1)} GB` : '')

export default function Settings({ status, onReset }: { status: Status; onReset: () => void }) {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [coversOn, setCoversOn] = useState(status.covers_online)
  useEffect(() => {
    get<Usage>('/usage').then(setUsage).catch(() => {})
  }, [])
  const c = status.catalog
  const lib = status.library
  const maxTps = Math.max(1, ...(usage?.bench?.rows.map((r) => r.prompt_tps) ?? [1]))
  return (
    <>
      <div className="top-strip drag-strip bar-solid" />
      <div className="settings-col rise-in">
        <span className="page-icon">
          <Tile color="var(--tile-grey)" size={56} icon={<GearFillIcon size={30} />} />
        </span>
        <h1 className="page-title">设置</h1>

        <h2 className="section-h">本机模型</h2>
        <div className="set-card">
          {status.models.map((m) => {
            const u = usage?.by_model.find((x) => x.model === m.name)
            return (
              <div key={m.key} className="set-row">
                <Tile color={m.key === 'big' ? 'var(--tile-indigo)' : 'var(--tile-blue)'} icon={<CpuFillIcon size={13} />} />
                <div className="set-main">
                  <div style={{ fontWeight: 500 }}>{m.name}</div>
                  <div className="t13 secondary">
                    {m.key === 'big' ? '定方向、挑片、整理口味画像' : '把你说的话整理成记录'}
                    {`。${m.file}，${gb(m.size_bytes)}，上下文 ${(m.ctx / 1024).toFixed(0)}K`}
                  </div>
                  {u && (
                    <div className="t13 secondary">
                      调用 {u.calls} 次，读入 {u.prompt_tokens.toLocaleString()} 个 token，生成 {u.completion_tokens.toLocaleString()} 个，平均每秒生成 {u.avg_gen_tps} 个
                    </div>
                  )}
                  {m.error && <div className="t13 danger">{m.error}</div>}
                </div>
                <span className="set-val flex items-center" style={{ gap: 6 }}>
                  <span className={`status-dot ${m.status === 'ready' ? 'ready' : m.status === 'loading' ? 'loading' : 'error'}`} />
                  {m.status === 'ready' ? '运行中' : m.status === 'loading' ? '加载中' : '不可用'}
                </span>
              </div>
            )
          })}
        </div>

        {usage?.bench && (
          <>
            <h2 className="section-h">长记忆读入速度</h2>
            <div className="t13 secondary">
              {usage.bench.model} 在 {usage.bench.machine} 上读入不同长度的记忆。第二次读同一段记忆时复用缓存，只算新增的部分。
            </div>
            <div className="set-card" style={{ padding: '4px 16px 12px' }}>
              <div className="bench">
                {usage.bench.rows.map((r, i) => (
                  <div key={r.ctx} className="bench-col" title={`首次 ${r.first_seconds}s，复用缓存 ${r.cached_seconds}s`}>
                    <span className="bench-num">{Math.round(r.prompt_tps)}</span>
                    <span
                      className="bench-bar"
                      style={{ height: Math.round((r.prompt_tps / maxTps) * 84), animationDelay: `${i * 60}ms` }}
                    />
                    <span className="t13 secondary">{r.ctx >= 1024 ? `${Math.round(r.ctx / 1024)}K` : r.ctx}</span>
                  </div>
                ))}
              </div>
              <div className="t13 secondary">每秒读入的 token 数。横轴是记忆长度。</div>
              <div className="t13 secondary" style={{ marginTop: 8 }}>
                {usage.bench.rows
                  .map((r) => `${Math.round(r.ctx / 1024)}K 首次 ${r.first_seconds} 秒，复用缓存 ${r.cached_seconds} 秒`)
                  .join('；')}
                。
              </div>
            </div>
          </>
        )}

        <h2 className="section-h">片库、书库和曲库</h2>
        <div className="set-card">
          <div className="set-row">
            <Tile color="var(--tile-indigo)" icon={<BooksFillIcon size={13} />} />
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>{c.available ? `${Number(c.total).toLocaleString()} 部影片和剧集` : '没有找到片库'}</div>
              <div className="t13 secondary">
                {c.available
                  ? `电影 ${Number(c.count_movie).toLocaleString()} 部，剧集 ${(Number(c.count_series) + Number(c.count_miniseries)).toLocaleString()} 部，${Number(c.with_zh).toLocaleString()} 部有中文名。来自 IMDb 非商业数据集，存在本机。`
                  : '运行 backend/scripts/build_catalog.py 生成片库。'}
              </div>
            </div>
          </div>
          <div className="set-row">
            <Tile color="var(--tile-teal)" icon={<BooksFillIcon size={13} />} />
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>
                {lib.available
                  ? `${Number(lib.count_book ?? 0).toLocaleString()} 本书，${Number(lib.count_album ?? 0).toLocaleString()} 张专辑`
                  : '书库和曲库还没有生成'}
              </div>
              <div className="t13 secondary">
                {lib.available
                  ? `来自 Wikidata（CC0），${lib.built_at ?? ''} 生成，存在本机，推荐时从这里筛候选。书库里没有的书和专辑，会按名字到豆瓣读书或 iTunes 查一下是否真的存在。`
                  : '运行 backend/scripts/build_library.py 生成。在那之前，书和音乐只靠联网按名字核实。'}
              </div>
            </div>
          </div>
        </div>

        <h2 className="section-h">隐私</h2>
        <div className="set-card">
          <div className="set-row">
            <Tile color="var(--tile-indigo)" icon={<LockFillIcon size={13} />} />
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>你的口味只在这台 Mac 上</div>
              <div className="t13 secondary">访谈、看过读过听过的记录、评语和口味画像都存在本机的一个文件里。没有账号，没有同步，没有使用统计。</div>
            </div>
          </div>
          <div className="set-row">
            <Tile color="var(--tile-teal)" icon={<WifiSlashFillIcon size={13} />} />
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>联网只查作品，不带你的信息</div>
              <div className="t13 secondary">
                片刻会按作品名去豆瓣、iTunes、Open Library 查封面，核实书名和专辑名。请求里只有作品名、作者或年份，没有你的话、评分和画像，也没有账号。
              </div>
            </div>
          </div>
          <div className="set-row">
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>联网获取封面</div>
              <div className="t13 secondary">关掉后只显示已经缓存的封面，其余用文字封面代替。</div>
            </div>
            <button
              className={`switch${coversOn ? ' on' : ''}`}
              role="switch"
              aria-checked={coversOn}
              onClick={async () => {
                const v = !coversOn
                setCoversOn(v)
                await put('/prefs', { covers_online: v })
                onReset()
              }}
            >
              <span />
            </button>
          </div>
        </div>

        <h2 className="section-h">你的数据</h2>
        <div className="set-card">
          <div className="set-row">
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>记忆文件</div>
              <div className="t13 secondary" style={{ wordBreak: 'break-all' }}>{status.data_path}</div>
            </div>
            <button className="pill-sm" onClick={() => window.pianke.reveal(status.data_path)}>
              在访达中显示
            </button>
          </div>
          <div className="set-row">
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>清空所有记忆</div>
              <div className="t13 secondary">删除访谈、全部记录、推荐历史和口味画像，回到第一次打开的样子。无法撤销。</div>
            </div>
            {confirm ? (
              <span className="flex" style={{ gap: 8 }}>
                <button className="pill-sm dim" onClick={() => setConfirm(false)}>
                  取消
                </button>
                <button
                  className="pill-sm danger"
                  onClick={async () => {
                    await post('/reset')
                    setConfirm(false)
                    onReset()
                  }}
                >
                  确认清空
                </button>
              </span>
            ) : (
              <button className="pill-sm danger" onClick={() => setConfirm(true)}>
                清空
              </button>
            )}
          </div>
        </div>
        <div className="t13 secondary" style={{ margin: '48px 0 0', textAlign: 'center' }}>
          片刻 0.1，Spark-X2.5 端侧模型创新挑战赛参赛作品
        </div>
      </div>
    </>
  )
}
