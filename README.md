# 片刻

**Fewer films, better nights.** 不刷信息流。只推荐三部，每一部都懂你。

片刻是一个 macOS 桌面应用，管三个书架：影视、书、音乐。它记住你看过、读过、听过什么，你打了几颗星、写了什么评语、当时是什么状态，然后在你问“今晚看什么”“下一本读什么”“现在听什么”的时候，只挑三部，并告诉你为什么是它们。两个 Spark-X2.5 模型、片库、书库和曲库都在你的 Mac 上。你的话、评分和口味画像不经过任何第三方；联网只用来按作品名查封面、核实书名和专辑名。

> Spark-X2.5 端侧模型创新挑战赛参赛作品。

## 为什么做片刻

短视频和流媒体的推荐系统优化的是停留时长，抓住的是“此刻还想继续刷”的冲动，而不是“看完觉得值”的那一面（Kleinberg、Mullainathan 和 Raghavan 2022 年的论文专门讨论过这种偏好不一致）。大语言模型能读懂人用自己的话说出来的偏好和理由，更适合做少而准的推荐。

这件事有一个矛盾：推荐越准，需要的私人上下文越多；上下文越私人，越不该交给云端。片刻把模型和记忆都放在本机，矛盾就不存在了。联网查作品信息时，请求里只有作品名、作者或年份这类公开信息，没有账号，也没有任何关于你的内容（见 `backend/pianke/lookup/net.py`，全部出站请求只从这里发出）。

口味常常跨越书影音：在电影里喜欢克制叙述的人，读小说时多半也是。协同过滤要靠同一个书架上的大量行为才能学到偏好，大语言模型读得懂“我喜欢它什么都没说出口”这样的话，可以把一个书架上学到的东西带到另一个书架。

## 它怎么工作

```
第一次打开   选书架（影视 / 书 / 音乐，可多选，没选的以后点开时再认识）
             → 封面墙：认出看过的，点一下是喜欢，点两下是不喜欢
               （认比回忆省力得多，而且每次点击都已经是核实过的作品）
             → 四个问题，从你点过的作品问起：它哪里打动你、那部为什么不喜欢、
               平时什么时候看和读、有什么绝对不碰
             → 4B 抽取对话里提到的作品 → 片库 / 书库 / 网上逐一核实 → 第一版口味画像

今晚看什么   你说一句今天的状态，选几个标签
  读画像     L2 口味画像 + L3 最近两周（长度固定，与历史多长无关）
  定方向     4B 把画像和今晚的要求变成片库筛选条件，并说出几部它想到的片
  核实       每部片名先在本地片库里核实，查不到的直接丢掉，界面上如实显示
  挑三部     4B 从候选清单里挑三部；JSON 语法约束只允许清单里的 id，
             “因为你说过”只允许指向你自己的记录，原话从数据库逐字读出

每一部推荐  “看过了”：看完了还是没看完、0 到 5 星（可拖动，半星）、评语、日期；
               星级只由你给，1.7B 只从评语里整理喜欢/不喜欢的方面、状态和同伴，
               原话逐字保存
             “没看”：选一个原因，每个原因写到不同的地方
               想看，先存着 → 片单 / 书单 / 歌单
               不感兴趣 / 知道它，不对胃口 → 带原因的负面记录，整理画像时会读
               今晚不合适 → 只进最近两周的近况，长期画像看不到它

第二天       “昨晚的《无间道》看了吗？” 加进片单的、或者那晚一部都没碰的，
             下次打开时问一次（书隔两周内，音乐两天内），可以答“还没顾上”

记录         每个书架一份自己的日志：画廊或表格，点开是可编辑的记录页
             （状态、星级、日期、来由、评语），改评语时 1.7B 重读一遍

整理画像     4B 把全部记录完整读一遍（这里用上长上下文），重写画像；
             每条结论都标出依据的片子；你改过的条目永远保留
```

### 分层记忆

| 层 | 内容 | 谁读 |
| --- | --- | --- |
| L0 事件 | 你说过、做过的一切，只追加 | 审计与导出 |
| L1 记录 | 每部作品一条：书架、状态、星级、喜欢与不喜欢的方面、情境、评语原话、日期、来由、不想看的原因 | 整理画像时全部读；推荐时只读相关的几条，同书架为主，再带几条别的书架里感受最强的 |
| L2 画像 | 自然语言口味画像，分“你偏爱的”“你会避开的”“书影音之间”“你的习惯”“最近的变化”，每条结论附依据，可编辑，有版本 | 每次推荐 |
| L3 近况 | 最近两周的记录与状态，包括“今晚不合适”跳过的作品 | 每次推荐 |

记录从 50 条涨到 5000 条，推荐的输入长度不变；长上下文只用在不赶时间的整理上。

### 两个模型的分工

| 模型 | 任务 | 理由 |
| --- | --- | --- |
| Spark-X2.5-4B | 访谈回应、定方向、挑片 / 挑书 / 挑专辑、整理画像 | 需要理解口味和长上下文 |
| Spark-X2.5-1.7B | 把评语整理成结构化记录 | 高频、低风险、要快 |

### 三个书架

| 书架 | 本地库（筛候选、封面墙） | 库里没有时联网核实 | 封面 |
| --- | --- | --- | --- |
| 影视 | IMDb 非商业数据集，4.6 万部，其中 3.2 万部有中文名 | TMDB（填了 Key 时），豆瓣 | TMDB（按 IMDb 编号），豆瓣，维基百科 |
| 书 | Wikidata（CC0）里的知名作品，含中文作品 | 豆瓣读书，iTunes Books | 豆瓣，维基百科，Open Library |
| 音乐（以专辑为单位） | Wikidata 里的知名专辑，含华语、日韩 | iTunes | 维基百科，Cover Art Archive，iTunes |

推荐管线三个书架共用：定方向时 JSON 语法只允许该书架存在的类型、语种或地区；模型想到的每部作品先查本地库，再按名字联网查，查不到的丢掉；挑选时 id 只能来自候选清单。

## 运行

需要 Apple 芯片的 Mac、[llama.cpp](https://github.com/ggml-org/llama.cpp) b10828 或更新版本（`brew install llama.cpp`）、Python 3.11、Node 22。

```bash
# 1. 模型（约 3.7 GB）
mkdir -p models && cd models
curl -LO https://huggingface.co/XHToken/Spark-X2.5-4B-GGUF/resolve/main/Spark-X2.5-4B-Q4_K_M.gguf
curl -LO https://huggingface.co/XHToken/Spark-X2.5-1.7B-GGUF/resolve/main/Spark-X2.5-1.7B-Q4_K_M.gguf
cd ..

# 2. 片库（下载 IMDb 非商业数据集约 1.9 GB，生成 43 MB 的 data/catalog.sqlite）
#    评分人数 3000 以上的都收；有中文译名的放宽到 300，华语片在 IMDb 上评分的人少
#    书库和曲库（从 Wikidata 拉取，生成 data/library.sqlite；没有它也能用，书和音乐只靠联网核实）
mkdir -p data/raw && cd data/raw
for f in title.basics title.ratings title.akas title.crew title.principals name.basics; do
  curl -LO https://datasets.imdbws.com/$f.tsv.gz; done
cd ../../backend
pip install -e ".[dev]"
python scripts/build_catalog.py
python scripts/build_library.py
python -m pytest -q

# 3. 桌面应用（会自动拉起后端和两个 llama-server）
cd ../app
npm install
PIANKE_PYTHON=$(which python) npm run dev
```

两个本机模型在第一次用到时才加载，打开应用不占内存；设 `PIANKE_PRELOAD=1` 可以在启动时就加载。

### 用 OpenAI 兼容接口代替本机模型

内存不够或不想下载模型时，在「设置 → 模型」里切到「OpenAI 兼容接口」，填接口地址（一般以 `/v1` 结尾）、API Key 和模型名。OpenAI、DeepSeek、OpenRouter 和本机的 Ollama、LM Studio 都可以用，这时第 1 步的模型和 llama.cpp 都不需要。不同服务支持的参数不一样，片刻会根据接口返回的 400 错误自动去掉或改名不支持的参数，结构化输出从 `json_schema` 依次退到 `json_object` 和纯提示词。

设置存在 `~/Library/Application Support/Pianke/settings.json`（权限 600），不在记忆文件里，清空记忆和导出都不会带上 API Key。用远程接口时，你的话、记录和口味画像会在聊天和推荐时发给那个服务，界面上的隐私说明会随之改变；接口在本机（localhost）时仍然算作不出这台 Mac。

### 联网服务（可选）

「设置 → 联网服务」里可以填：

- **TMDB API Key**：电影海报按 IMDb 编号直接从 TMDB 取，一次请求，比按片名搜豆瓣快得多。在 themoviedb.org 免费申请，v3 Key 和 v4 Read Access Token 都可以。没填时仍用豆瓣和维基百科。
- **Exa 或 Tavily**：填了搜索 Key 后，推荐会多做三件事：定方向时模型写一两个搜索词，从结果里找新作和冷门作品，再和其他候选一样核实；书库、豆瓣、iTunes 都查不到的书和专辑，用搜索核实是否存在；挑好之后搜每一部的评价，把推荐理由改写得更具体。每次推荐多 3 到 5 次搜索和两次模型调用。

专辑封面先查网易云音乐（不需要 Key，约 0.2 秒一张），再查维基百科、Cover Art Archive 和 iTunes。启动时会在后台把你的记录和最近推荐过的作品的封面先取下来。

### 打包成 Mac 应用

```bash
cd app
PIANKE_PYTHON=$(which python3.11) npm run dist
```

依次做三件事：用 PyInstaller 把 Python 后端打成独立程序（`scripts/build-backend.sh`，用自己的 `backend/.venv`，不改动你的 Python 环境）；用 electron-builder 生成 `release/mac-arm64/片刻.app`；用 macOS 自带的 hdiutil 生成 `release/片刻-0.1.0-arm64.dmg`（`scripts/make-dmg.sh`）。打开 dmg，把「片刻」拖进「应用程序」即可。

安装包约 400 MB，包含界面、后端、片库和书库，不含模型。用本机模式时，把两个 gguf 放进 `~/Library/Application Support/Pianke/models/`，或者在那里建一个指向已有模型目录的链接；用 OpenAI 兼容接口时不需要模型。后端日志在同目录的 `backend.log`。应用没有签名，只在打包的这台 Mac 上直接打开；拷到别的 Mac 上要右键选「打开」。

### 发布更新

装好的片刻启动后和之后每 6 小时读一次 GitHub Releases 上最新的 `latest.json`。有新版本时，侧栏「设置」旁边亮一个蓝点，设置页顶部可以下载。应用分四部分，各有一个指纹，只下载指纹变了的部分：

| 部分 | 内容 | 压缩后 |
| --- | --- | --- |
| app | 界面和主进程（app.asar） | 约 1.3 MB |
| backend-src | 后端的 Python 源码 | 约 0.06 MB |
| runtime | 冻结的 Python 和第三方库 | 约 19 MB，只在依赖变了时下载 |
| data | 片库和书库 | 约 24 MB，只在重建片库后下载 |

下载完点「重启并更新」，片刻退出，一个小脚本把这几部分换进 `片刻.app`，再重新打开。Electron 版本变了的更新要下载完整 dmg。没有用 electron-updater：它在 Mac 上要求应用签名。

发一个新版本：

```bash
cd app
# 1. 把 package.json 的 version 改大，比如 0.1.0 → 0.1.1
PIANKE_PYTHON=$(which python3.11) npm run dist            # 2. 打包
npm run release -- --notes "这次改了什么"                    # 3. 生成 release/update/，先看一眼
npm run release -- --notes "这次改了什么" --publish          # 4. 上传到 GitHub Releases
```

runtime 的指纹由 Python 版本、`pip freeze` 和后端用到的模块列表算出，不看文件本身（PyInstaller 每次打包的字节都不一样）。打包时会在冻结的环境里把后端每个模块导入一遍，缺库会在这一步报错。

图标的源文件是 `app/scripts/icon.svg`，改了之后运行 `npx electron scripts/make-icon.mjs` 重新生成 `build/icon.icns`。

用户数据只存在 `~/Library/Application Support/Pianke/user.sqlite`。同目录下的 `cache.sqlite` 和 `covers/` 只放公开的作品信息和封面，可以随时删除。

## 实测（Apple M3 Pro，18GB，2026-10-05）

**长记忆读入速度**（Spark-X2.5-4B Q4_K_M，llama.cpp Metal，`scripts/bench_speed.py`）

| 记忆长度 | 首次读入 | 每秒读入 | 再次读同一段（复用缓存） |
| --- | --- | --- | --- |
| 4K | 9.8 秒 | 457 token | 0.32 秒 |
| 16K | 41 秒 | 401 token | 0.93 秒 |
| 32K | 97 秒 | 340 token | 0.70 秒 |
| 64K | 261 秒 | 253 token | 2.2 秒 |
| 122K | 726 秒 | 170 token | 1.4 秒 |

1600 条记录约 12 万 token，首次读完要 12 分钟。所以推荐只读固定长度的画像，长上下文留给不赶时间的整理；记录按时间顺序追加，整理时前缀可以复用缓存。

**消融**（`scripts/eval_ablation.py`）

| 实验 | 结果 |
| --- | --- |
| 让模型直接说片名，能在本地片库核实的比例（8 个请求，各 6 部） | 4B 79%，1.7B 19% |
| 观后感整理：观看状态准确率 / 评分误差在 1 以内 / 原话逐字摘录（12 条手标） | 1.7B 83% / 83% / 100%，平均 0.9 秒；4B 92% / 100% / 100%，平均 1.8 秒 |
| 挑片时不加 id 枚举约束，选出清单外 id 的比例（24 次） | 0%，与加约束相同；约束是保证，不是这次观察到的修正 |

1.7B 自由生成的片名多半不存在（例如《风之谷·海岸线》），4B 也有约两成核实不了，所以每个片名都要过片库。观后感交给 1.7B 是取舍：它快一倍，偶尔判错状态，但用户原话逐字保存，4B 整理画像时重读的是原话，结构化字段只是索引；4B 在后台整理长记忆的几分钟里，1.7B 仍能即时响应。

## 评测脚本

```bash
cd backend
python scripts/bench_speed.py      # 4B 读入 4K 到 120K 记忆的速度，首次与复用缓存
python scripts/eval_ablation.py    # 片名幻觉、id 约束、1.7B 与 4B 整理观后感的对比
```

结果写在 `data/bench_speed.json` 和 `data/eval_ablation.json`，设置页会画出读入速度。

演示录屏可以用界面驱动脚本自动操作应用并截图：

```bash
cd app && npx electron-vite build
PIANKE_HOME=/tmp/pianke-demo PIANKE_DRIVE=scripts/drive/onboard.json PIANKE_SHOTS=/tmp/shots npx electron .
PIANKE_HOME=/tmp/pianke-demo PIANKE_DRIVE=scripts/drive/main.json PIANKE_SHOTS=/tmp/shots npx electron .
PIANKE_HOME=/tmp/pianke-demo PIANKE_DRIVE=scripts/drive/shelves.json PIANKE_SHOTS=/tmp/shots npx electron .
```

## 目录

```
backend/pianke/
  llm/        llama-server 进程管理（用时加载）、OpenAI 兼容接口、带 JSON 约束的调用、每次调用的耗时记录
  catalog/    片库（IMDb）、书库和曲库（Wikidata）：核实、条件检索、封面墙
  lookup/     唯一联网的地方：按作品名查书、专辑和封面，联网搜索（web.py），结果缓存在本机
  memory/     L0–L2 的 SQLite 存储
  domains.py  三个书架的措辞、回访周期、“没看”的原因和它们写到哪里
  flows/      冷启动、推荐、看过 / 没看、回访、画像整理
  server.py   FastAPI，只监听 127.0.0.1
backend/scripts/  片库与书库构建、测速、消融评测
app/          Electron + React 桌面应用
```

## 致谢

- 模型：[Spark-X2.5](https://huggingface.co/collections/XHToken/spark-x25)（词元星火），由 [llama.cpp](https://github.com/ggml-org/llama.cpp) 在本机运行。
- 片库：[IMDb Non-Commercial Datasets](https://developer.imdb.com/non-commercial-datasets/)，仅用于个人与非商业用途；中文片名经 [OpenCC](https://github.com/BYVoid/OpenCC) 转为简体。
- 书库和曲库：[Wikidata](https://www.wikidata.org/)（CC0）。封面与联网核实：豆瓣、iTunes Search API、维基百科、Open Library、Cover Art Archive，仅按作品名或公开编号查询。
- 界面沿用 Clover 的设计语言：Notion 式阅读区、macOS 通高侧栏、系统字体。
