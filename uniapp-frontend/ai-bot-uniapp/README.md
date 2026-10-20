# AI Bot 前端 —— uni-app + Vue3 版

原站前端是 `web/index.html` 里的一份原生 HTML + CSS + JavaScript 单页应用。
本项目把它完整移植为 **uni-app + Vue3 + TypeScript + Pinia**，
一套代码同时构建 H5 与微信小程序。

> **当前对齐的是 v2**（121,872 字节 / 40 KB 样式 / 58 KB 逻辑），
> 相对 v1（61,068 字节）新增了角色设定、个人设置、流式暂停/停止、
> 会话搜索与收藏标签、代码块弹窗、消息时间与重新生成等一整套功能。
> 详见文末「v2 更新内容」。

界面按「与原站一致」为目标逐像素校准过：1440×900 下与原站 v2 截图对比，
**差异像素 736 / 1296000 = 0.057%**，关键元素的 `getBoundingClientRect()`
误差全部 ≤ 1px（剩余差异主要是顶栏随机会话 ID 与角色下拉的占位文本）。

---

## 一、快速开始

```bash
# 依赖（必须用 pnpm，且必须启用 hoisted 链接器，见下文「已知坑」）
pnpm install

# H5 开发
pnpm dev:h5          # http://127.0.0.1:5178

# 微信小程序开发：产物在 dist/dev/mp-weixin，用微信开发者工具打开该目录
pnpm dev:mp-weixin

# 生产构建
pnpm build:h5        # 产物 dist/build/h5
pnpm build:mp-weixin # 产物 dist/build/mp-weixin
```

### 小程序 / App 的后端地址（必做）

`.env` 不会提交到仓库，克隆后需要自己建一份：

```bash
cp .env.example .env
# 编辑 .env，把 VITE_API_BASE_URL 改成你的后端地址
```

- **真机调试**：填电脑的局域网 IP（手机和电脑同一网络），例如
  `VITE_API_BASE_URL=http://192.168.1.10:8000`；换网络后要改并重新构建。
- **正式发布**：必须是 HTTPS 域名，并在微信公众平台「开发管理 → 服务器域名」
  加入 request 合法域名；HTTP / 局域网 IP 只能用于开发调试。
- **AppID**：`src/manifest.json` 的 `mp-weixin.appid` 需要换成自己的 AppID，
  否则构建产物是 `touristappid`，只能做本地预览，不能真机预览/上传。

开发时 `/api` 由 Vite 代理到后端（见 `vite.config.ts`，默认
`http://127.0.0.1:8000`）。生产部署需要让 H5 与后端同源，或在网关把 `/api`
反代到 FastAPI —— 与原站的 `web/dev_server.py` 是同一个思路。

> 注：微信小程序的 `wx.request` 不支持 PATCH，所以会话改名/收藏标签/角色切换/
> 角色编辑/默认角色这几个接口在 MP 上走 **PUT**；后端为它们同时注册了 PUT 别名。

## 二、目录结构

```
src/
├── api/
│   ├── request.ts        统一请求封装（Bearer 注入 / 401 处理 / 错误信息归一化 / multipart 上传）
│   └── index.ts          各业务接口与类型定义
├── components/
│   ├── AppRail.vue           左侧导航 + 账号区
│   ├── AppTopbar.vue         顶栏（含会话标题内联编辑）
│   ├── WelcomePanel.vue      欢迎区（首屏 / 新会话 / 空历史 三种形态）
│   ├── MessageItem.vue       单条消息气泡
│   ├── ChatHistoryPanel.vue  对话页右侧「历史对话」面板
│   ├── DocumentsView.vue     我的资料（上传 / 统计 / 资料库）
│   ├── HistoryView.vue       历史会话
│   ├── AuthScreen.vue        登录 / 注册浮层
│   ├── ApprovalModal.vue     人工审批弹窗（Human in the loop）
│   └── NoticeToast.vue       全局提示条
├── pages/index/index.vue 唯一的页面：三个工作区靠 `hidden` 类切换，与原站一致
├── stores/               Pinia：auth / chat / docs / ui
├── styles/app.scss       原站样式表的移植产物（由脚本生成，勿手改）
├── utils/
│   ├── format.ts         时间 / 文件大小 / HTML 转义 / 上传预校验
│   ├── markdown.ts       Markdown 渲染（H5 出 HTML，小程序出内联样式的节点树）
│   ├── stream.ts         SSE 流式对话（H5 fetch / 小程序 enableChunked / App 降级）
│   └── thread.ts         会话 ID 生成（含 crypto.randomUUID 降级）
├── static/               头像与发送图标
├── manifest.json         各端配置
├── pages.json            页面与窗口配置
└── uni.scss              主题变量（取自原站 :root 调色板）
```

工作区根目录另有两个辅助目录：

- `references/original-split/` —— 从原站 `index.html` 拆出的 CSS / HTML / JS，
  是移植的唯一事实来源。
- `tools/` —— 样式移植与验证脚本（见第五节）。
- `references/shots/` —— 与原站的对比截图与差分报告。

## 三、移植是怎么做的

### 1. 样式：脚本化逐条转换，而不是手抄

原站样式表 1792 行，手抄必然出错，因此由 `tools/build_styles.py` 自动转换。
页面组件刻意沿用**与原站完全相同的 class 名**，让这份样式表能原样生效。
脚本只改动 uni-app / 小程序无法处理的部分：

| 原站写法 | 移植后 | 原因 |
| --- | --- | --- |
| `:root` / `body` / `html` | `:root, page` | uni-app 的页面根元素是 `page` |
| `h1` `p` `strong` `dt` `dd` `img` `svg` `nav` | 对应的类选择器 | uni-app 只渲染 `<view>` / `<text>`，没有这些原生标签 |
| `width: min(1040px, 100%)` | `width: 100%; max-width: 1040px` | `min()` 在小程序 / 旧内核不可靠 |
| `max-width: min(88%, 860px)` | `max-width: 88%` + `@media (min-width: 978px)` | 等价改写 |
| `rgb(33 56 47 / 7%)` | `rgba(33, 56, 47, 0.07)` | 空格分隔 + 斜杠透明度语法兼容性差 |
| `inset: 0` | `top/right/bottom/left: 0` | 同上 |
| `.decision-option:has(input:checked)` | `.decision-option.is-active` | 小程序不支持 `:has()`，改由 Vue 状态驱动 |
| 原生 `<input type="file">` 规则 | 删除，改用 `.file-picker` | uni-app 用 `uni.chooseFile` / `uni.chooseMessageFile` |
| `.markdown-body p` 等 | **保留** | H5 端 Markdown 用 `v-html` 注入，这些是真标签 |

### 2. 滚动容器

小程序里 `overflow: auto` 不产生滚动，必须用 `<scroll-view>`；而 uni-app 的
`scroll-view` 会多包一层滚动壳。原站是把盒模型直接放在滚动容器上的，因此把
`display: flex/grid` + `gap` + `padding` 下移到内层 `.messages-inner` /
`.chat-history-titles-inner`，否则内层滚动壳会被压成内容高度而无法滚动。

### 3. Markdown 的两种承载方式

- **H5**：与原站完全一致，把 Markdown 生成的 HTML 注入气泡（`v-html`），
  由 `.markdown-body` 的样式表接管，链接可点击。
- **小程序 / App**：`<rich-text>`。它不认外部 CSS 类，所以
  `renderMarkdownNodes()` 把样式**内联进每个节点**。
- 另外，`rich-text` 在 H5 上会丢弃 `<a>` 的 `href`（链接不可点），
  这也是 H5 端不走 `rich-text` 的原因。

### 4. 流式对话

| 平台 | 实现 |
| --- | --- |
| H5 | `fetch` + `ReadableStream`，手动解析 SSE |
| 微信小程序 | `uni.request({ enableChunked: true })` + `onChunkReceived`，自带跨分片 UTF-8 解码 |
| App | 无可靠流式通道，降级为普通 `POST /chat` 一次性返回 |

解析规则严格按接口文档：按 `\n\n` 分帧、保留不完整的尾片段、`line.slice(6)`
取 `data:` 内容、`[DONE]` 即停、JSON 解析失败时按原样当作文本增量。

## 四、与原站的差异（含发现的问题与修复）

界面刻意保持 1:1，下面是**行为层面**的改动。前 8 条是原站的真实缺陷，
最后 3 条是安全与工程建议。

| # | 问题 | 影响 | 修复 |
| --- | --- | --- | --- |
| 1 | `makeThreadId()` 直接调用 `crypto.randomUUID()` | 该 API 只在 https / localhost 存在。用局域网 IP 走 http 打开时它是 `undefined`，「新建会话」直接抛 TypeError，功能完全不可用 | `utils/thread.ts` 增加降级实现 |
| 2 | 422 校验错误被显示成 `[object Object]` | 原站 `throw new Error(detail)`，而 FastAPI 的 `detail` 是数组时会被强制转成 `"[object Object]"`，用户看到无意义报错（接口文档 §7 明确要求区分两种形态） | `api/request.ts` 中数组取 `detail[0].msg` |
| 3 | 从未调用 `/auth/me`，全局上传入口对所有人开放 | 普通用户在「使用范围」里能选「所有用户可用」，选了只会拿到 403（接口文档 §2.3 / §6.1 要求据 `is_admin` 隐藏或禁用） | 登录后拉 `/auth/me`；非管理员只能选「仅自己可用」 |
| 4 | 删除资料按钮无权限判断 | 别人的私有资料、非管理员看到的全局资料，删除按钮都可点，点了必然 403（接口文档 §6.3 要求按权限可点） | 按 `owner_id` + `is_admin` 判定，无权时禁用 |
| 5 | 上传前无扩展名 / 大小预校验 | 接口文档 §6.1 把预校验列为前端职责（20MB、5 种格式），原站要等后端 413 / 415 才知道 | 本地预校验并给中文提示 |
| 6 | 删除「当前会话」后消息区不刷新 | 原站只换 `threadId`，屏幕继续显示已删除的对话内容，标题栏也还是旧的 | 走完整重置流程 |
| 7 | 审批弹窗忽略 `review_configs[].allowed_decisions` | 后端规定每个动作允许哪些决定，原站三个按钮写死，不允许的决定也能点，点了才报错 | 按 `allowed_decisions` 禁用不可用项；后端没给则全部可用（与原站行为一致） |
| 8 | SSE 收到 `[DONE]` 后不结束读取 | 原站 `continue` 而非 `break`。若服务端在 DONE 后不断开连接（keep-alive / 代理缓冲），界面会永远停在 busy | 收到 `[DONE]` 立即结束 |
| 9 | **Markdown 的 XSS 防线** | 原站靠 `marked` + DOMPurify 运行时净化，链路有效但小程序端跑不了 DOMPurify | 改为源头禁用：`markdown-it({ html: false })`，模型输出里的 `<script>` 等一律转义为文本（已用 51 条断言验证，含 `<script>` / `<iframe>` / `<img onerror>` / `javascript:` 链接） |
| 10 | **token 存在 localStorage** | 与 #9 叠加：任何 XSS 都能直接读走 7 天有效期的 JWT。这是原站与移植版**共有**的取舍 | 未改变存储方式（为兼容同一后端与旧前端的 `ai_bot_token` 键），但把访问收敛到 `api/request.ts` 一处。**若本项目要上公网，建议后端改用 httpOnly + SameSite Cookie**，届时只需改这一个文件 |
| 11 | 代码块无语法着色 | 原站用 `marked` 不做高亮，代码块是单色的 | 移植版接入了 highlight.js（仅注册 13 种常用语言以控制小程序包体），但**刻意没有引入任何 hljs 主题**，以保持与原站一致的观感。想要彩色代码块，只需在 `app.scss` 里补一套 `.hljs-*` 配色 |

另外，原站样式表里有 `.side` / `.side-heading` / `.side-caption` / `.side-divider` /
`.upload-options` 等一组**在 HTML 里已经没有对应元素**的历史遗留规则
（原站自己也不用），移植时原样保留了。要清理的话可以安全删除。

## 五、验证方式（可复现）

`tools/` 下的脚本构成一条完整的对比链路：

```bash
# 1. 从原站 index.html 拆出 CSS / HTML / JS（事实来源）
python tools/split_reference.py

# 2. 重新生成 uni-app 样式表
python tools/build_styles.py

# 3. 复制原站资源、并按原站 SVG 几何重绘发送图标
python tools/build_assets.py
```

对比验证：

```bash
# 把原站与移植版放到同一 origin，用 iframe 同时加载并读取真实几何数据
python tools/build_compare.py
python -m http.server 4182 --bind 127.0.0.1 --directory references/compare-root

# 元素坐标差异报告（应输出 "(none)"）
msedge --headless=new --window-size=1000,760 \
  --virtual-time-budget=9000 --screenshot=references/shots/geometry.png \
  http://127.0.0.1:4182/measure.html

# 逐像素差分
python tools/diff_shots.py        # references/shots/diff.png + diff-report.txt
python tools/measure_offsets.py   # 分区域偏移量

# 气泡内 Markdown 的渲染检查（往真实页面注入等价 DOM）
msedge --headless=new --window-size=1440,760 \
  --virtual-time-budget=12000 --screenshot=references/shots/markdown-bubble.png \
  http://127.0.0.1:4182/markdown-check.html
```

当前基线：`differing pixels: 457 / 1296000 (0.04%)`，几何报告 `(none)`。

## 六、已知坑与注意事项

### pnpm 必须用 hoisted 链接器

`pnpm-workspace.yaml` 里设置了 `nodeLinker: hoisted`。pnpm 默认的隔离式
`node_modules` 不会把 `@dcloudio/uni-shared`、`module-alias`、`xregexp` 等
提升到顶层，`uni` CLI 启动即 `MODULE_NOT_FOUND`。这是 DCloud 官方给出的
pnpm 配置。

### 样式里不要写 `input` / `textarea` 标签选择器

uni-app 编译时会把它们改写成 `uni-input` / `uni-textarea`（组件元素自身）。
写成 `.composer-input textarea` 会变成 `.composer-input uni-textarea`，
而后代选择器永远不命中。且 `uni-textarea` 默认 `height: 150px`，
多行输入框必须显式给高度。

### 原站是 `<button>` 的地方需要补居中

浏览器会给 `<button>` 的文字做水平 + 垂直居中，换成 `<view>` 后两者都丢，
必须显式用 flex 补回来（`tools/build_styles.py` 的 EXTRA 段已处理）。

### 尚未验证的部分

- **微信小程序端与 App 端只验证到「编译通过 + 条件编译分支正确」**，
  没有在微信开发者工具或真机上跑过。两端都没有可用的模拟器 / 设备环境。
  已确认：mp-weixin 产物使用 `<rich-text nodes>`、不含 `v-html`、
  不含 SSE 流式的 H5 分支。
- **没有连真实后端做过运行时验证**：登录、SSE 增量、202 审批往返、
  multipart 上传 body、各工作区数据加载，都只做了静态与逻辑核对。
  需要按第一节启动后端后自行联调。

---

## 七、v2 更新内容

v2 的前端从 61 KB 涨到 122 KB，新增了五个区域。移植时**全部按本仓库后端的
真实实现**对齐（契约逐条读自 `app/api.py`、`app/routers/auth.py`、
`app/routers/settings.py`、`app/chat_streams.py`），而不是照 `接口文档.md`，
因为文档有多处滞后。

### 新增的界面

| 区域 | 内容 |
| --- | --- |
| 导航 | 3 项 → 5 项：新增「角色设定」「个人设置」 |
| 对话页 | 顶部「本会话角色」下拉 +「应用角色最新版」；输入框旁**暂停 / 继续 / 停止**；顶栏**导出 Markdown** |
| 消息 | 气泡时间（悬浮显示完整时间）、助手耗时行、复制、**重新生成**、代码块浮层「复制 / 全屏」 |
| 历史页 | 标题搜索、标签筛选、全部 / 收藏夹、收藏 ★、标签编辑 |
| 角色设定（新） | 左侧角色编辑器（名称 / 定位 / 语气 / 风格 / 边界 + 实时预览），右侧角色库（系统预设可复制） |
| 个人设置（新） | 总览 + 模型连接 / 账户安全 / 界面与输入 三个二级页；进入设置时整页隐藏左侧栏与顶栏（`settings-mode`） |
| 代码弹窗（新） | 全屏查看代码，替代原站的原生 `<dialog>` |

### 后端契约里必须注意的几点

1. **`POST /auth/password`（不是 PATCH）、`PUT /settings/model`（不是 POST）**
   —— 用错动词会得到 405。
2. **422 有两种形态**：schema 校验失败是 `{detail: string, errors: []}`，
   业务规则失败是 `{detail: string}`。永远不要按 `detail[0]` 去取。
3. **SSE 帧比 v1 复杂**：首帧 `{"type":"started","turn_id":…}`、增量
   `{"delta":…}`、审批帧只有 `status`、结束 `{"type":"done","elapsed":…}`、
   `{"type":"error","detail":…}`、`{"type":"cancelled"}`、`[DONE]`，
   以及 `: keepalive` 心跳注释帧。每帧前面还有 `id: N` 行。
   本移植的 `utils/stream.ts` 已按这套协议重写。
4. **`turn_id` 由客户端生成**并随 `/chat/stream` 一起提交（后端接受），
   暂停 / 继续 / 停止都用它。回合结束后这些接口返回
   `404 生成任务不存在或已结束` —— 这只代表这一轮结束了。
5. **暂停不会立刻停止模型**：后端只是关掉 SSE 发送闸门，生成仍在继续、
   队列填满后才反压。真正省钱要用「停止」。
6. **`PATCH /personas/{id}` 是整体替换**，省略 `style_rules`/`constraints`
   会被清空，所以移植版始终发送五个字段。
7. **模型连接只接受公网 HTTPS 443**，本机 / 内网 / `*.local` 一律拒绝；
   API Key 从不下发前端，`configured` 是唯一信号。
8. **标签**最多 8 个、每个 1~24 字，返回的是后端去重后的结果。

### 这一版没做的

- **导出会话为图片**。原站用 canvas 现场合成整段对话（头像、气泡、Markdown、
  代码块），H5 与小程序要各写一套；按钮保留了，点击会明确提示未实现。
  「导出 Markdown」是完整可用的。
- **App（plus）端没有实际验证**。`build:app` 目前会因 Vue 版本 dedupe 失败，
  `pnpm-workspace.yaml` 里已用 `overrides` 把 `@vue/*` 锁到 3.5.43 规避，
  但尚未装 `@dcloudio/uni-app-plus` 实测；如有需要再补。

### 验证数据

| 指标 | v2 结果 |
| --- | --- |
| `vue-tsc --noEmit` | exit 0，零错误 |
| `build:h5` / `build:mp-weixin` | 均 DONE |
| 与原站 v2 的截图差异（桌面 1440×900） | 795 / 1,296,000 = **0.061%** |
| 关键元素几何误差 | 消息区 / 欢迎区 / 角色栏 / 输入区等全部一致（`getBoundingClientRect` 逐项对齐） |

---

## 八、移动端适配（uni-app 尺寸体系）

样式分两层，互不干扰：

| 文件 | 作用域 | 尺寸体系 |
| --- | --- | --- |
| `src/styles/app.scss` | **≥1024px** 桌面布局 | px，逐像素对齐原站 |
| `src/styles/adaptive.scss` | **<1024px** 移动布局 | **rpx**（750 设计基准） |

之所以分两层而不是把 px 全量转成 rpx：原站是桌面三栏布局
（232px 侧栏 + 内容 + 258px 历史面板），把 `232px` 机械换成 `464rpx`
会占掉手机 62% 的屏宽，布局必然崩。移动端需要的是**另一套结构**，
所以适配层是重写而不是单位换算。

### 移动端做了什么

- **左侧栏 → 底部 tab 栏**：5 个工作区用 `grid-template-columns: repeat(5, 1fr)`
  等分，保证一定塞得进屏宽；选中态用顶部 4rpx 小横条 + 主色文字。
- **账号与退出登录挪到顶栏**：左侧栏变成 tab 栏后底部没地方放账号区，
  移动端在顶栏右侧给一个退出图标（`.topbar-logout`，桌面端 `display:none`）。
- **尺寸全部 rpx**：字号 48/40/34/28/26/24/22/20rpx 成体系；间距 20~32rpx；
  圆角 8~20rpx。`1px` 描边仍用 px（hairline），否则高倍屏会变粗。
- **触摸目标 ≥ 72rpx**：按钮、tab、表单项、审批选项统一抬高。
- **安全区**：底部 tab 栏、输入区、提示条都加了
  `constant/env(safe-area-inset-bottom)`，适配刘海屏。
- **气泡宽度 78%**：手机上一行太长会难读。
- **单列化**：资料 / 历史 / 角色 / 设置页全部单列堆叠，双栏布局在窄屏展开。
- **输入区**：多行框 120rpx、可扩到 320rpx；发送键 72×68rpx。

### 踩过的坑

1. **横向溢出会把 tab 栏和弹窗裁掉**。`page` 上加 `overflow-x: hidden`，
   角色栏（`.chat-persona-bar`）必须允许收缩（`min-width: 0` + `overflow: hidden`），
   否则会话角色名一长整页就被撑宽。
2. **tab 栏用 flex 等分不可靠**，5 个中文标签容易被挤出屏宽，改用 grid 5 等分。
3. **无头浏览器截图不能直接当手机视口用**：`--window-size=390,844` 截出来的
   图是 390px，但页面实际按更宽的视口布局，看起来像被裁切。正确做法是用
   固定 390px 的 iframe 承载页面再截图，或者用脚本读
   `documentElement.scrollWidth` / `getBoundingClientRect()` 校验
   —— 本项目两种都用了，最终 `scrollWidth` 必须等于 390。

## 九、运行限制

- **小程序选文件**：`wx.chooseMessageFile` 只能从聊天会话选择文件，不能浏览
  手机文件系统。要上传本机资料，先把文件发到“文件传输助手”，再回到资料页选择。
  页面里已有对应提示。
- **PATCH**：小程序的 `wx.request` 不支持 PATCH，会话改名/收藏标签/角色切换/
  角色编辑/默认角色在 MP 上走 PUT（后端同时注册了 PUT 别名）。
- **流式暂停/停止**：`app/chat_streams.py` 的状态在进程内存里，多 worker 部署
  时需要单 worker 或粘性会话，否则暂停/停止可能返回 404（前端会当成“这一轮已结束”）。
- **胶囊避让**：小程序自定义导航会按 `getMenuButtonBoundingClientRect()` 的真实
  位置给顶栏留空间（`--capsule-space`）；换基础库/机型后如果仍有遮挡，先检查
  这个变量是否注入成功。



