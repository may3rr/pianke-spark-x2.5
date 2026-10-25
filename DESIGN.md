设计规范（必须严格执行）

气质沿用 Clover 的设计语言（见 README 致谢）：Notion 的内容区 + macOS 的窗口壳——通高系统侧栏（原生 vibrancy）、透明底侧栏图标、安静的排版。片刻在这层底座上叠了自己的三样东西：作品名用衬线展示字、三个书架各有一个色相、封面是最大的视觉元素。克制、留白充足，一屏只做一件事。

### 6.1 字体

- **只用系统字体：** `font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", system-ui, sans-serif;` 英文自动用 SF Pro，中文自动用苹方。禁止引入任何网络字体或自带字体文件。
- **唯一的例外是作品名**：`--serif: "Songti SC", "STSong", "Hoefler Text", "Iowan Old Style", serif`（`.film-name`，600，`letter-spacing: 0.01em`）。片名、书名、专辑名和封面占位标题用它；界面其余部分不碰衬线。
- **层级只靠字重区分。** 可用字重：400、500、600、700。
- **字号六档：**
  - `13px`：次要文字——计数、说明、组标签、属性行标签、chip。
  - `15px`：界面文字（body 默认；按钮、列表行、属性值、侧栏行）。
  - `17px`：阅读区——推荐理由、模型说的方向、对话气泡、评语输入框（行高 1.6–1.7）。
  - `20px`：区块标题（600，上间距 32px）。
  - `26px`：空状态 / 运行页大标题（600）。
  - `32px`：页面标题（700，`.page-title`）。
  - 六档之外唯一的例外：顶栏 tab 用 14px。
- 计数、耗时、进度一律 `font-variant-numeric: tabular-nums`（body 已全局设置）；全局禁斜体（base.css 用 `!important` 压掉一切 UA 斜体）。
- 主文字颜色 `--text`；次要信息（计数、说明、caption、组标签）用 `--text-secondary`。语义色只用于状态。
- 禁止全大写标签，禁止在标题里单独给某个词加粗或变色（语义计数除外），禁止用中点连接元信息（用中文逗号），按钮文字后面不加箭头，中文标题旁不放英文小字标签。

### 6.2 颜色（`app/src/renderer/src/styles/tokens.css` 是唯一来源）

tokens.css 中允许十六进制和 rgba；组件里禁止任何颜色字面量，只能引用变量。调色板是 Notion 暖中性色：

```css
:root {
  --bg: #ffffff;  --bg-subtle: #f7f7f5;
  --text: #37352f;  --text-secondary: rgba(55,53,47,0.65);
  --accent: #2383e2;                     /* 唯一的交互强调色：主按钮、选中态、焦点环 */
  --fill: rgba(55,53,47,0.06);           /* hover */
  --fill-strong: rgba(55,53,47,0.09);    /* 选中行（中性灰胶囊） */
  --sidebar-tint: rgba(247,247,245,0.55); /* 侧栏叠色，透出 vibrancy */
  --separator: rgba(0,0,0,0.1);          /* 侧栏与内容区之间唯一的线 */
  --glass-edge / --glass-shadow          /* 封面与候选行的 0.5px 细边 / 浮起 */
  /* 语义图形色 = macOS 系统色：#FF5F57 / #FEBC2E / #28C840（浅），
     #FF6961 / #FFC53D / #32D74B（深）；--*-tint 是同色 ~0.2 alpha（深 ~0.28）；
     圆点、tile、勾选、进度条、spinner 都用这一组 */
  --high / --medium / --ok / --*-tint
  /* 语义文本色 = 可读变体：#D70015 / #A05A00 / #1E7E34（浅），深色同图形色 */
  --high-text / --medium-text / --ok-text
  --low = --text-secondary;  --low-tint = --fill-strong;
  /* 书架与功能色相（tile 底色，非语义色——语义色只表达状态）：
     indigo #5856D6、blue #007AFF、teal #30B0C7、purple #AF52DE、
     pink #D6409F、grey #8E8E93，dark 用深色系统色变体 */
  --tile-indigo/blue/teal/purple/pink/grey
  /* 品牌色（设置页供应商图标，LobeHub 品牌色）：
     --brand-qwen / --brand-deepseek；品牌色块上的白色 glyph 用 --on-brand */
  --shimmer                 /* 占位微光 */
  --ease: cubic-bezier(0.2, 0.8, 0.2, 1) /* 唯一缓动 */
}
/* dark：--bg #191919 等，同名定义在 tokens.css */
```

- **书架色相：** 影视 indigo、书 teal、音乐 pink，唯一来源是 `lib/domains.ts` 的 `DOMAINS[d].color`。pink 取偏品红的 `#D6409F` 而不是 macOS 的 `#FF2D55`——后者与语义红只差十几度，会被读成"严重问题"。
- **功能 tile：** 运行页四步固定为 读画像 purple、定方向 indigo、核实 teal、挑选 blue；引导页 隐私 lock indigo、模型 cpu blue、本地库 books teal、联网 wifi purple。
- **封面占位底色不进 tokens：** 按标题字符哈希生成色相（`Cover.tsx`，`(h*31+c)%360`，种子 17），经 `--cover-hue` 传给 CSS。
- 深浅色跟随系统（`prefers-color-scheme`），不提供手动切换；两套同名定义都在 tokens.css。

### 6.3 不加没有意义的线条

- **禁止分割线、边框、描边、下划线装饰。** 区块之间靠留白和底色区分。例外只有三处半：侧栏与内容区之间一条 `1px var(--separator)` 发丝线（用 box-shadow 画，不用 border）；顶栏下方那条线只在下面滚动时渐现（`.strip-edge`）；同组卡片内行与行之间的 `-1px` 发丝线（如 checkin 的相邻行）。最后半处是封面和候选行的 `--glass-edge` 0.5px 细圈——它和 `--glass-shadow` 一起构成"纸片浮起"的卡片感，仍然不画 border。
- 选中与 hover 一律用柔和底色：hover `--fill`，选中行 `--fill-strong`。唯一允许的"圈选"是引导页的书架选择（`.domain-pick.on`：accent 10% 底 + 1.5px accent 圈）。
- 阴影只允许 `--glass-edge` / `--glass-shadow`（封面、候选行、占位纸片）和浮层菜单；窗格和普通面板不加阴影。
- **焦点环只在真实键盘焦点出现**（`:focus-visible`，`--accent` 2px，这是唯一允许的"线"）。不要在加载或鼠标点击后程序化 focus 元素。
- **内容可选、控件不可选：** 标题、理由、对话、记录、画像都能选中拷贝；按钮、chip、封面墙等控件由 base.css 统一划掉 user-select，双击封面不会带出一片选区。
- 不要把内容切成一排排一模一样的圆角卡片；推荐结果的三部之间只用 48px 留白分开。

### 6.4 间距、圆角、动效

- 间距只用这组值：4 / 8 / 12 / 16 / 24 / 32 / 48 px（48px 是页面左右边距和结果区的大节距；组件内部微调允许 2/6/10/14，不许出第三套值）。
- 圆角：列表行 / 小面板 / 引用块 8px；卡片 / 输入区 / checkin 12px；小色块与音乐封面 6px；封面等其余 4px；胶囊（按钮、chip）980px；`.tile` 圆角 = 尺寸 × 0.27（macOS Settings 的观感）。侧栏是通高直边窗格，没有圆角。
- 动效曲线统一 `var(--ease)`；时长：hover/press 160ms、面板与入场（`.rise-in`）240ms、屏幕切换 360ms（`::view-transition-group(*)` 全局一条）、长列表入场用 80–120ms 一步的 `animationDelay` 阶梯。只允许 transform / opacity（骨架条加 scaleX）。
- 屏幕切换与状态页翻转一律走 `document.startViewTransition`（`lib/vt.ts` 的 `morph()`；reduced-motion 或不支持时退化为直接切换）。
- 尊重 `prefers-reduced-motion`：base.css 全局把 transition/animation 压到 0.01ms，`morph()` 再兜一层。
- 等待与完成各有唯一形态，不要发明新的：等待是 Spinner（accent 弧线，0.8s）或 `cc-shimmer` 微光；完成是 CheckDraw（圆底 + 白勾描画动画）。

### 6.5 窗口

- `titleBarStyle: 'hiddenInset'`，红绿灯 (20, 20) 融进 52px 的 drag-strip，条内按钮设 no-drag；窗口 `vibrancy: 'sidebar'`，根节点透明，每个区域自己画底色。
- 侧栏 240px 通高直边（`.glass-sidebar`，`--sidebar-tint` 透出 vibrancy）；主内容区从 240px 起，页面 max-width 720px（`.page-wide` 880px），内边距 8px 48px 96px；顶栏 52px sticky。
- 默认 1280 × 820，最小 1040 × 700。
- `backgroundThrottling: false`：演示录屏和截图依赖它，窗口被遮挡时 `screencapture` 才能拿到新帧；录制时主进程用 `data-window-focus` 保持"聚焦"外观。

### 6.6 文案

- 简体中文，主动语态，动词开头。按钮写清楚会发生什么："挑三部""整理我的口味"，不写"提交"。
- 不道歉，不用感叹号，不写营销腔。
- 三个书架的措辞差异（看过/读过/听过、片单/书单/歌单、今晚/接下来/现在、没看完/没读完/没听完）全部以 `lib/domains.ts` 的 `DOMAINS` 为唯一来源（后端镜像在 `backend/pianke/domains.py`）；新界面不许散落硬编码这些词。
- 用户原话逐字引用，不改写；引用块固定结构：原话 + 「你说《…》的话」。隐私提示跟着设置走：本机时"你的话和记录只在这台 Mac 上"，远程接口时点名 host（`lib/models.ts` 的 `models()`）。
- 空状态和错误都要告诉用户下一步怎么做。例如："本机模型还没有准备好。稍等几秒再试一次。""本地服务出了问题：……。退出后重新打开片刻。"

### 6.7 图标与插画

- 只用自绘的内联 SVG，SF Symbols 风格 **filled**（`fill="currentColor"`，`components/Icons.tsx` 的 `Fill`，24×24 viewBox）；颜色只走 CSS 变量。描边只留给勾选描画（CheckDraw）和齿轮齿角的圆角处理。禁止图标字体和图标库。
- 侧栏图标用透明底实心 glyph（`.side-ic`，20px 框、17px 字形）：中性图标 `--text-secondary`，选中行变 `--text`；三个书架图标带色相（`.side-ic-hue`，取 `DOMAINS[d].color`），窗口失焦时整体降饱和（`:root[data-window-focus='false']`）。
- 其余位置（运行页、引导页、结果页）用 `.tile`：默认 22px 圆角色块，白色实心 glyph + 色相底，分配见 6.2。
- 封面宽高比固定：影视 2:3、书 0.7、音乐 1:1（`DOMAINS.aspect`）。取不到封面或还在加载时用排版封面占位：衬线标题（11–18px 随宽度）+ 创作者（宽 ≥90px 才显示），底色见 6.2；圆角音乐 6px、其余 4px。
- 星级是 26px 五星、半星步进、可点击可拖动（最左 18% 是 0 星死区）；"未评分"（null）与 0 星是两回事，只有清除按钮能到 null。

### 6.8 代码对应

- `styles/tokens.css`：颜色与缓动的唯一来源；`styles/base.css`：全局规则（字体、焦点环、reduced-motion、drag-strip、pill、tile、side-ic、callout）；`styles/app.css`：各屏幕的样式。
- `lib/domains.ts` 书架措辞、色相与封面宽高比；`lib/vt.ts` 视图切换；`components/Icons.tsx` 图标与 Tile；`components/Cover.tsx` 封面与占位；`components/StarRating.tsx` 星级。
- 窗口参数（BrowserWindow、vibrancy、红绿灯位置）在 `app/src/main/index.ts`。
