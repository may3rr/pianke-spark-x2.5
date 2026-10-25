import { useEffect, useState } from 'react'
import { get, post, put, type LlmSettings, type Status } from '../lib/api'
import { modelDot, modelStatusLabel } from '../lib/models'
import { hasUpdate, mb, useUpdate } from '../lib/update'
import { setDemo, useDemo } from '../lib/demo'
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

export default function Settings({ status, onReset, embedded = false }: { status: Status; onReset: () => void; embedded?: boolean }) {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [coversOn, setCoversOn] = useState(status.covers_online)
  const demo = useDemo()
  useEffect(() => {
    get<Usage>('/usage').then(setUsage).catch(() => {})
  }, [])
  const c = status.catalog
  const lib = status.library
  const maxTps = Math.max(1, ...(usage?.bench?.rows.map((r) => r.prompt_tps) ?? [1]))
  return (
    <>
      {!embedded && <div className="top-strip drag-strip bar-solid" />}
      <div className="settings-col rise-in">
        <span className="page-icon">
          <Tile color="var(--tile-grey)" size={56} icon={<GearFillIcon size={30} />} />
        </span>
        <h1 className="page-title">设置</h1>
        <UpdateCard />

        <h2 className="section-h">模型</h2>
        <ModelSource llm={status.llm} onSaved={onReset} />
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
                    {m.provider === 'api'
                      ? `。经 ${m.host} 调用`
                      : `。${[m.file, gb(m.size_bytes), `上下文 ${(m.ctx / 1024).toFixed(0)}K`, '用到时才加载'].filter(Boolean).join('，')}`}
                  </div>
                  {u && demo && (
                    <div className="t13 secondary">
                      调用 {u.calls} 次，读入 {u.prompt_tokens.toLocaleString()} 个 token，生成 {u.completion_tokens.toLocaleString()} 个，平均每秒生成 {u.avg_gen_tps} 个
                    </div>
                  )}
                  {m.error && <div className="t13 danger">{m.error}</div>}
                </div>
                <span className="set-val flex items-center" style={{ gap: 6 }}>
                  <span className={`status-dot ${modelDot(m)}`} />
                  {m.provider === 'api' ? (m.status === 'ready' ? '接口' : '未配置') : m.status === 'ready' ? '运行中' : modelStatusLabel(m)}
                </span>
              </div>
            )
          })}
          <div className="set-row">
            <div className="set-main">
              <div style={{ fontWeight: 500 }}>演示模式</div>
              <div className="t13 secondary">
                打开后，推荐页、画像页和这里会写出模型名称、用时和读入的 token 数，方便演示模型在本机运行。平时用不到。
              </div>
            </div>
            <button className={`switch${demo ? ' on' : ''}`} role="switch" aria-checked={demo} onClick={() => setDemo(!demo)} data-demo>
              <span />
            </button>
          </div>
        </div>

        {demo && usage?.bench && (
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

        <h2 className="section-h">联网服务</h2>
        <OnlineServices llm={status.llm} onSaved={onReset} />

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
              <div style={{ fontWeight: 500 }}>{status.llm.search_on ? '联网查作品，也联网搜索' : '联网只查作品，不带你的信息'}</div>
              <div className="t13 secondary">
                片刻会按作品名去 TMDB、豆瓣、网易云音乐、iTunes、Open Library 查封面，核实书名和专辑名，请求里只有作品名、作者或年份。
                {status.llm.search_on && '开了联网搜索后，模型根据你这次的要求写出的搜索词会发给搜索服务。'}
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
        <VersionFooter />
      </div>
    </>
  )
}

interface TestResult {
  model: string
  ok: boolean
  answer?: string
  seconds?: number
  error?: string
}

/** Local Spark-X2.5, or any OpenAI-compatible endpoint. The key is write-only:
 *  the backend keeps it and only ever sends back a hint. */
function ModelSource({ llm, onSaved }: { llm: LlmSettings; onSaved: () => void }) {
  const [mode, setMode] = useState(llm.mode)
  const [baseUrl, setBaseUrl] = useState(llm.base_url)
  const [key, setKey] = useState('')
  const [big, setBig] = useState(llm.big_model)
  const [small, setSmall] = useState(llm.small_model)
  const [busy, setBusy] = useState<'' | 'save' | 'test'>('')
  const [results, setResults] = useState<TestResult[] | null>(null)
  const [err, setErr] = useState('')
  const dirty =
    mode !== llm.mode || baseUrl !== llm.base_url || key !== '' || big !== llm.big_model || small !== llm.small_model
  const loopback = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])[:/]/.test(baseUrl)

  const save = async (m = mode) => {
    setBusy('save')
    setErr('')
    setResults(null)
    try {
      await put('/llm', {
        mode: m,
        base_url: baseUrl,
        api_key: key === '' ? null : key,
        big_model: big,
        small_model: small,
        ctx: llm.ctx,
      })
      setKey('')
      onSaved()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  const test = async () => {
    if (dirty) await save()
    setBusy('test')
    setResults(null)
    try {
      setResults((await post<{ results: TestResult[] }>('/llm/test')).results)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="set-card" style={{ padding: '12px 16px' }}>
      <div className="seg">
        {(
          [
            ['local', '本机 Spark-X2.5'],
            ['api', 'OpenAI 兼容接口'],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            className={mode === k ? 'on' : ''}
            onClick={() => {
              setMode(k)
              // switching back to local needs nothing else; apply it at once
              if (k === 'local' && llm.mode !== 'local') save('local')
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {mode === 'local' ? (
        <div className="t13 secondary" style={{ marginTop: 8 }}>
          两个 Spark-X2.5 模型在本机运行，用到时才加载。你说的话不出这台 Mac。
        </div>
      ) : (
        <>
          <div className="t13 secondary" style={{ marginTop: 8 }}>
            OpenAI、DeepSeek、OpenRouter 这类服务，或本机的 Ollama、LM Studio，只要兼容 OpenAI 的
            /chat/completions 接口都可以用。
          </div>
          <label className="field">
            <span className="field-label">接口地址</span>
            <input
              className="field-input"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              spellCheck={false}
            />
            <div className="field-hint">一般以 /v1 结尾。Ollama 填 http://localhost:11434/v1</div>
          </label>
          <label className="field">
            <span className="field-label">API Key</span>
            <input
              className="field-input"
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={llm.has_key ? `已保存（${llm.key_hint}），留空则不改` : loopback ? '本机服务一般不需要' : 'sk-...'}
              spellCheck={false}
              autoComplete="off"
            />
            <div className="field-hint">只存在本机的 settings.json 里，清空记忆和导出都不会带上它。</div>
          </label>
          <label className="field">
            <span className="field-label">主模型</span>
            <input
              className="field-input"
              value={big}
              onChange={(e) => setBig(e.target.value)}
              placeholder="gpt-4.1-mini、deepseek-chat、qwen3:8b"
              spellCheck={false}
            />
            <div className="field-hint">访谈、定方向、挑选、整理口味画像。</div>
          </label>
          <label className="field">
            <span className="field-label">轻量模型（可选）</span>
            <input
              className="field-input"
              value={small}
              onChange={(e) => setSmall(e.target.value)}
              placeholder={big || '留空则和主模型相同'}
              spellCheck={false}
            />
            <div className="field-hint">把你写的感受整理成记录，调用最频繁，可以用便宜快速的模型。</div>
          </label>
          {!loopback && baseUrl && (
            <div className="t13" style={{ marginTop: 12, color: 'var(--text-secondary)' }}>
              用这个接口时，你的话、记录和口味画像会在聊天和推荐时发给 {baseUrl.replace(/^https?:\/\//, '').split('/')[0]}
              。片刻自己仍然只在本机保存它们。
            </div>
          )}
          <div className="flex items-center" style={{ gap: 8, marginTop: 12 }}>
            <button className="pill-sm" disabled={!dirty || !!busy} onClick={() => save()}>
              {busy === 'save' ? '正在保存' : '保存'}
            </button>
            <button className="pill-sm" disabled={!baseUrl || !big || !!busy} onClick={test}>
              {busy === 'test' ? '正在测试' : dirty ? '保存并测试' : '测试连接'}
            </button>
          </div>
        </>
      )}
      {err && <div className="t13 danger" style={{ marginTop: 8 }}>{err}</div>}
      {results?.map((r) => (
        <div key={r.model} className={`t13 ${r.ok ? 'secondary' : 'danger'}`} style={{ marginTop: 8 }}>
          {r.ok ? `${r.model} 可以用，${r.seconds} 秒回答了「${r.answer}」。` : `${r.model}：${r.error}`}
        </div>
      ))}
    </div>
  )
}

/** TMDB for film posters, Exa or Tavily for web search. Keys are write-only. */
function OnlineServices({ llm, onSaved }: { llm: LlmSettings; onSaved: () => void }) {
  const [tmdb, setTmdb] = useState('')
  const [provider, setProvider] = useState(llm.search_provider)
  const [searchKey, setSearchKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const keyName = provider === 'exa' ? 'exa_key' : 'tavily_key'
  const savedHint = provider ? llm.keys[keyName] : ''
  const dirty = tmdb !== '' || searchKey !== '' || provider !== llm.search_provider

  const saveAndTest = async () => {
    setBusy(true)
    setNote('')
    try {
      if (dirty) {
        await put('/services', {
          tmdb_key: tmdb === '' ? null : tmdb,
          search_provider: provider,
          ...(provider && searchKey !== '' ? { [keyName]: searchKey } : {}),
        })
        setTmdb('')
        setSearchKey('')
        onSaved()
      }
      const r = await post<{ tmdb?: boolean; search?: string }>('/services/test')
      const parts = []
      if (r.tmdb !== undefined) parts.push(r.tmdb ? 'TMDB 可以用' : 'TMDB 没查到海报，检查 Key')
      if (r.search !== undefined) parts.push(r.search ? `搜索可以用，搜到「${r.search}」` : '搜索没有结果，检查 Key')
      setNote(parts.join('；') || '已保存')
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="set-card" style={{ padding: '12px 16px' }}>
      <label className="field" style={{ marginTop: 0 }}>
        <span className="field-label">TMDB API Key（电影海报）</span>
        <input
          className="field-input"
          type="password"
          value={tmdb}
          onChange={(e) => setTmdb(e.target.value)}
          placeholder={llm.keys.tmdb_key ? `已保存（${llm.keys.tmdb_key}），留空则不改` : 'v3 API Key 或 v4 Read Access Token'}
          spellCheck={false}
          autoComplete="off"
        />
        <div className="field-hint">
          按 IMDb 编号直接取海报，一次请求，比按片名搜豆瓣快得多。在 themoviedb.org 的账户设置里免费申请。没填时用豆瓣和维基百科。
        </div>
      </label>
      <div className="field">
        <span className="field-label">联网搜索</span>
        <div className="seg">
          {(
            [
              ['', '不用'],
              ['exa', 'Exa'],
              ['tavily', 'Tavily'],
            ] as const
          ).map(([k, label]) => (
            <button key={k} className={provider === k ? 'on' : ''} onClick={() => setProvider(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {provider && (
        <label className="field">
          <span className="field-label">{provider === 'exa' ? 'Exa' : 'Tavily'} API Key</span>
          <input
            className="field-input"
            type="password"
            value={searchKey}
            onChange={(e) => setSearchKey(e.target.value)}
            placeholder={savedHint ? `已保存（${savedHint}），留空则不改` : provider === 'exa' ? 'Exa API Key' : 'tvly-...'}
            spellCheck={false}
            autoComplete="off"
          />
        </label>
      )}
      <div className="field-hint" style={{ marginTop: 8 }}>
        开了以后推荐会多做三件事：定方向时联网找新作和冷门作品；书库和网上都查不到的书、专辑，用搜索核实是否存在；挑好之后搜它们的评价，把理由写得更具体。每次推荐多 3 到 5 次搜索和两次模型调用。
      </div>
      <div className="flex items-center" style={{ gap: 8, marginTop: 12 }}>
        <button className="pill-sm" disabled={busy || (!dirty && !llm.keys.tmdb_key && !llm.search_on)} onClick={saveAndTest}>
          {busy ? '正在测试' : dirty ? '保存并测试' : '测试'}
        </button>
        {note && <span className="t13 secondary">{note}</span>}
      </div>
    </div>
  )
}

/** Shown at the top of Settings while there is an update to act on. */
function UpdateCard() {
  const u = useUpdate()
  if (!hasUpdate(u) && u.status !== 'error') return null
  if (u.status === 'error' && !u.version) return null
  return (
    <div className="set-card update-card" style={{ padding: '12px 16px', marginBottom: 8 }}>
      <div className="flex items-center" style={{ gap: 12 }}>
        <span className="update-dot" style={{ marginLeft: 0 }} />
        <div className="set-main">
          <div style={{ fontWeight: 500 }}>
            {u.status === 'ready' ? `${u.version} 已下载好` : `有新版本 ${u.version}`}
            <span className="secondary" style={{ fontWeight: 400 }}>{`，当前 ${u.current}`}</span>
          </div>
          <div className="t13 secondary">
            {u.status === 'available' && `只需下载有变化的部分，共 ${mb(u.size)}。`}
            {u.status === 'downloading' && `正在下载 ${mb(u.received)} / ${mb(u.size)}`}
            {u.status === 'ready' && '重启片刻就会换上新版本，你的记录不受影响。'}
            {u.status === 'full' && '这个版本换了底层运行环境，需要下载完整安装包。'}
            {u.status === 'error' && u.error}
          </div>
          {u.notes && u.status !== 'downloading' && (
            <div className="t13" style={{ marginTop: 6, whiteSpace: 'pre-line' }}>{u.notes}</div>
          )}
        </div>
        {u.status === 'available' && (
          <button className="pill-sm" onClick={() => window.pianke.update.download()} data-update-download>
            下载更新
          </button>
        )}
        {u.status === 'ready' && (
          <button className="pill-sm" onClick={() => window.pianke.update.apply()} data-update-apply>
            重启并更新
          </button>
        )}
        {u.status === 'full' && (
          <button className="pill-sm" onClick={() => window.pianke.update.openPage()}>
            去下载
          </button>
        )}
        {u.status === 'error' && (
          <button className="pill-sm" onClick={() => window.pianke.update.check()}>
            重试
          </button>
        )}
      </div>
    </div>
  )
}

function VersionFooter() {
  const u = useUpdate()
  const note =
    u.status === 'checking' ? '正在检查更新' : u.status === 'none' ? '已是最新版本' : u.status === 'error' ? '检查更新失败' : ''
  return (
    <div className="t13 secondary" style={{ margin: '48px 0 0', textAlign: 'center' }}>
      片刻 {u.current}，Spark-X2.5 端侧模型创新挑战赛参赛作品
      {u.current && (
        <>
          {' · '}
          {note || (
            <button className="link-accent t13" onClick={() => window.pianke.update.check()}>
              检查更新
            </button>
          )}
        </>
      )}
    </div>
  )
}
