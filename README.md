# AI-bot

一个面向学习场景的智能知识助手。项目基于 LangChain 与 LangGraph 实现
Agent，通过 PostgreSQL/pgvector 持久化会话、长期记忆与文档向量，并提供
RAG 检索、工具调用、人工审批、流式对话和多用户隔离能力。

本项目既是可运行的课程设计，也是一个用于学习 LangChain/LangGraph 核心能力的
完整实践：从模型接入、上下文工程、记忆系统和 RAG，到 API、前端、测试与 Docker
部署均包含在同一仓库中。

## 核心能力

- **LangGraph Agent**：统一编排模型、工具、状态和人工审批流程。
- **上下文工程**：动态注入核心记忆与相关记忆，长对话自动摘要压缩。
- **短期记忆**：使用 LangGraph PostgreSQL Checkpointer 保存会话状态，可恢复历史会话继续聊天。
- **长期记忆**：通过 PostgreSQL Store 与向量检索实现跨会话用户记忆，并按重要程度治理。
- **RAG 知识库**：支持 PDF、TXT、Markdown、DOCX、PPTX，完成解析、切分、Embedding、检索和引用。
- **人在回路**：写入长期记忆前暂停执行，由用户选择允许、拒绝或补充处理意见。
- **工具调用**：包含当前时间、记忆读写、知识库检索、网页搜索和网页正文提取。
- **多用户隔离**：JWT 登录认证；会话、私有资料和记忆均按用户隔离。
- **图片消息**：每轮最多 5 张、单会话最多 20 张；前端压缩后以 base64 data URL 发送，后端转换为多模态内容块交给模型。
- **多端前端**：uni-app（Vue 3 + TypeScript）提供 H5、微信小程序和 App 三端；仓库同时保留原生 HTML/JS 网页端。
- **离线演示兜底**：模型或网络异常时自动使用 50+ 条本地 mock 回答并标注；个人设置中可手动切换「真实模型 / Mock 离线模拟」。
- **流式输出**：通过 SSE 将 Agent 回复实时推送到网页端。
- **LangSmith 可观测性**：可选开启 Agent 全链路 tracing，查看模型、工具、延迟、错误与会话线程。
- **会话管理**：查看、恢复、重命名和删除历史会话。
- **会话组织**：按更新时间倒序列出会话，支持标题倒排搜索、收藏夹和标签。
- **角色设定**：系统预设与用户自建角色均可管理；会话保存角色快照，切换从下一条消息生效，不追溯修改旧消息。
- **导出**：B/S 前端支持将会话导出为 Markdown 或浏览器图片下载。
- **个人设置**：模型连接、修改密码、外观与输入、回答来源切换，以及清除本地缓存（本地存储 + 图片预览临时文件）。
- **Docker 部署**：前端、后端和 pgvector 数据库可通过 Docker Compose 一键启动。

## 系统架构

```mermaid
flowchart LR
    U[浏览器 / 小程序 / App] --> F[前端<br/>原生 Web :4173<br/>uni-app H5 :5178]
    F -->|/api| B[FastAPI 后端<br/>:8000]
    U -.->|小程序 / App 直连局域网| B
    B --> A[LangGraph Agent]
    A --> M[DeepSeek 对话模型]
    A --> T[Agent Tools]
    T --> W[网页搜索与抓取]
    T --> E[DashScope Embedding]
    A --> P[(PostgreSQL + pgvector)]
    P --> C[会话 Checkpoint]
    P --> L[长期记忆]
    P --> R[文档与向量片段]
```

一次聊天请求会经历以下过程：

1. JWT 鉴权并将外部 `thread_id` 绑定到当前用户。
2. 从 Checkpointer 恢复当前会话的消息和 Agent 状态。
3. 注入用户核心记忆，并根据当前问题语义检索相关长期记忆。
4. 模型按需调用时间、记忆、RAG 或联网工具。
5. 有副作用的记忆写入触发人工审批；批准后才继续执行。
6. 最终回复通过 SSE 流式返回，并将新状态持久化到 PostgreSQL。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Agent | LangChain 1.x、LangGraph 1.x |
| 模型 | DeepSeek（OpenAI-compatible API） |
| Embedding | DashScope Qwen Embedding，1024 维 |
| 后端 | Python 3.11-3.13、FastAPI、Uvicorn |
| 数据层 | PostgreSQL 16、pgvector、SQLAlchemy、psycopg 3 |
| 文档解析 | PyMuPDF、python-docx、python-pptx |
| 前端（Web） | HTML、CSS、原生 JavaScript、Marked、DOMPurify |
| 前端（多端） | uni-app、Vue 3、TypeScript、Pinia、Vite |
| 认证 | JWT、bcrypt |
| 部署 | Docker、Docker Compose |
| 测试 | pytest、FastAPI TestClient |

## 项目结构

```text
AI-bot/
├── app/
│   ├── agent/              # Agent、动态提示词和中间件
│   ├── memory/             # 短期记忆与长期记忆
│   ├── rag/                # 文档解析、切分、入库与检索
│   ├── routers/            # 认证与文档接口
│   ├── tools/              # Agent 可调用工具
│   ├── api.py              # FastAPI 主入口与会话接口
│   ├── auth.py             # JWT 与密码处理
│   ├── db_init.py          # 幂等数据库初始化
│   ├── embeddings.py       # 共享 Embedding 客户端
│   └── models.py           # SQLAlchemy 数据模型
├── uniapp-frontend/
│   └── ai-bot-uniapp/      # uni-app 多端前端（H5 / 微信小程序 / App）
├── web/
│   ├── assets/             # 头像与前端依赖
│   ├── dev_server.py       # 静态页面服务与同源 API 代理
│   └── index.html          # 原生网页端应用
├── tests/                  # 认证、会话、记忆与 RAG 测试
├── Dockerfile              # 后端镜像
├── web/Dockerfile          # 前端镜像
├── docker-compose.yml      # 前端、后端、数据库编排
├── pyproject.toml          # Python 项目与依赖配置
└── .env.example            # 环境变量模板
```

## 快速开始

### 1. 环境要求

- Git
- Docker Desktop 或 Docker Engine + Docker Compose
- 可访问 DeepSeek 与 DashScope API 的网络

### 2. 获取项目

```powershell
git clone https://github.com/weheh2233/AI-bot.git
cd AI-bot
```

### 3. 配置环境变量

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

Linux/macOS：

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
DEEPSEEK_API_KEY=你的模型密钥
DASHSCOPE_API_KEY=你的向量模型密钥
JWT_SECRET_KEY=一个足够长的随机字符串
```

可用下面的命令生成 JWT 密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` 已加入 `.gitignore`，不要把真实密钥提交到仓库。

### 4. 启动全部服务

```powershell
docker compose up -d --build
```

首次构建需要下载 Python、LangChain 和文档解析依赖，后续启动会复用镜像缓存。
后端会在数据库健康后自动创建 `vector` 扩展、业务表、LangGraph Checkpoint
表与长期记忆表。

### 5. 访问服务

| 服务 | 地址 |
| --- | --- |
| 网页端（原生） | <http://127.0.0.1:4173> |
| uni-app H5（开发） | <http://127.0.0.1:5178> |
| Swagger API 文档 | <http://127.0.0.1:8000/docs> |
| 后端健康检查 | <http://127.0.0.1:8000/health> |
| PostgreSQL | `127.0.0.1:5432` |

确认容器状态：

```powershell
docker compose ps
```

`postgres`、`backend`、`frontend` 均显示 `healthy` 后即可使用。

## 环境变量

| 变量 | 是否必需 | 默认值/用途 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | 对话模型密钥 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 否 | 对话模型名，默认 `deepseek-flash` |
| `DASHSCOPE_API_KEY` | 是 | Qwen Embedding 密钥 |
| `DASHSCOPE_BASE_URL` | 否 | DashScope OpenAI-compatible 地址 |
| `ZHIPUAI_API_KEY` | 否 | 联网搜索密钥；不配置时网页搜索工具不可用 |
| `JWT_SECRET_KEY` | 是 | JWT 签名密钥，建议至少 32 个字符 |
| `MAX_UPLOAD_BYTES` | 否 | 单文件上传上限，默认 `5MB` |
| `MODEL_SETTINGS_ENCRYPTION_KEY` | 否 | 加密个人模型 API Key；未配置时只能使用服务器默认模型 |
| `MAX_IMAGES_PER_REQUEST` | 否 | 每轮图片上限，默认 `5` |
| `MAX_IMAGES_PER_THREAD` | 否 | 单会话图片上限，默认 `20` |
| `LANGSMITH_TRACING` | 否 | 设为 `true` 后启用 LangSmith tracing，默认关闭 |
| `LANGSMITH_API_KEY` | 启用 tracing 时是 | LangSmith API Key，不要提交到仓库 |
| `LANGSMITH_PROJECT` | 否 | Trace 所属项目，默认建议使用 `ai-bot` |
| `LANGSMITH_ENDPOINT` | 否 | 默认 `https://api.smith.langchain.com` |
| `LANGSMITH_WORKSPACE_ID` | 否 | Key 可访问多个 workspace 时用于指定目标 workspace |
| `POSTGRES_DB` | 否 | 默认 `ai_bot` |
| `POSTGRES_USER` | 否 | 默认 `ai_bot` |
| `POSTGRES_PASSWORD` | 否 | 默认 `ai_bot_password`，非本地环境请修改 |

Compose 会根据 PostgreSQL 配置自动生成容器内 `DATABASE_URL`，无需在 `.env`
里写 `localhost` 数据库地址。

## LangSmith 可观测性

项目使用 LangChain/LangGraph 原生 tracing，不需要在每个模型和工具上手工埋点。
在 LangSmith 创建 API Key 后，把下面配置加入本地 `.env`：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=你的_LangSmith_Key
LANGSMITH_PROJECT=ai-bot
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

重启后端并完成一轮聊天，然后到 LangSmith 的 `ai-bot` 项目查看 trace。普通聊天、
流式聊天、重新生成和人工审批恢复分别使用可识别的 run name；同一应用会话通过内部
`thread_id` 聚合为 LangSmith Thread。未配置 Key 或保持 `LANGSMITH_TRACING=false`
时，项目仍可正常运行，不会上传 trace。

Tracing 会包含模型输入/输出、动态提示词、工具参数和工具返回值。即使项目已有 API
Key 脱敏中间件，也应把 LangSmith 当作可能含用户对话与检索内容的外部观测系统，
按实际数据合规要求决定是否启用、成员权限与保留周期。

## 记忆与 RAG

### 记忆分层

| 数据 | 存储方式 | 生命周期 |
| --- | --- | --- |
| 当前会话消息与 Agent 状态 | LangGraph PostgreSQL Checkpointer | 随会话保留，可恢复继续聊天 |
| 用户长期记忆 | PostgreSQL Store + pgvector | 跨会话保留，按用户隔离 |
| 会话标题 | `conversations` 业务表 | 独立于摘要状态，避免标题漂移 |

长期记忆分为 `core`、`normal`、`transient`。核心身份信息常驻上下文，普通记忆
根据当前问题做语义检索；写入记忆前会进入人工审批。

### 文档知识库

支持格式：

- `.pdf`：按页解析，检索结果保留页码。
- `.txt` / `.md`：按 UTF-8 文本解析。
- `.docx`：提取正文段落。
- `.pptx`：提取幻灯片中的文本框内容。

上传时可以选择：

- `private`：仅上传者可见。
- `global`：所有用户可见，仅管理员可上传或删除。

文档不会依赖本地文件路径进行检索；解析后的元数据、文本片段和向量全部写入
PostgreSQL。扫描版 PDF 如果没有文字层，将无法提取正文，需要先进行 OCR。

## API 总览

除 `/health`、`/auth/register` 和 `/auth/login` 外，业务接口均需要：

```http
Authorization: Bearer <access_token>
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/auth/register` | 注册并返回 JWT |
| `POST` | `/auth/login` | 登录并返回 JWT |
| `GET` | `/auth/me` | 获取当前用户 |
| `POST` | `/chat` | 普通聊天 |
| `POST` | `/chat/stream` | SSE 流式聊天 |
| `POST` | `/chat/resume` | 提交人工审批决定并恢复 Agent |
| `POST` | `/chat/turns/{turn_id}/pause` | 暂停流式生成 |
| `POST` | `/chat/turns/{turn_id}/resume` | 继续流式生成 |
| `POST` | `/chat/turns/{turn_id}/cancel` | 停止流式生成 |
| `GET` | `/conversations` | 会话列表 |
| `GET` | `/conversations/{thread_id}` | 会话详情与待审批状态 |
| `PATCH` | `/conversations/{thread_id}` | 修改会话标题 |
| `DELETE` | `/conversations/{thread_id}` | 删除会话及其 Checkpoint |
| `POST` | `/documents` | 上传并向量化文档 |
| `GET` | `/documents` | 获取当前用户可见文档 |
| `DELETE` | `/documents/{doc_id}` | 删除有权限操作的文档 |
| `GET/POST` | `/personas` | 角色列表与创建 |
| `PATCH/DELETE` | `/personas/{id}` | 修改或删除自建角色 |
| `GET/PATCH` | `/users/me/default-persona` | 读取或设置默认角色 |
| `GET/PUT/DELETE` | `/settings/model` | 个人模型连接配置 |
| `POST` | `/settings/model/test` | 测试个人模型连接 |

完整请求结构和在线调试入口见 Swagger：<http://127.0.0.1:8000/docs>。

## 本地开发

Docker 是推荐运行方式。需要直接运行 Python 代码时：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
docker compose up -d postgres
```

在 `.env` 中为宿主机进程补充：

```dotenv
DATABASE_URL=postgresql://ai_bot:ai_bot_password@127.0.0.1:5432/ai_bot
```

初始化并启动后端：

```powershell
python -m app.db_init
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload
```

另开终端启动前端代理：

```powershell
python -m uvicorn web.dev_server:app --host 127.0.0.1 --port 4173 --reload
```

uni-app 前端（H5 / 微信小程序 / App）：

```powershell
cd uniapp-frontend/ai-bot-uniapp
pnpm install
pnpm dev:h5         # H5，默认 127.0.0.1:5178，/api 代理到 8000
pnpm dev:mp-weixin  # 微信小程序，产物导入微信开发者工具
pnpm dev:app        # App，产物导入 HBuilderX
```

小程序 / App 不经过 Vite 代理，需要把 `uniapp-frontend/ai-bot-uniapp/.env`
里的 `VITE_API_BASE_URL` 改成电脑的局域网地址（例如
`http://192.168.1.10:8000`），并让 uvicorn 监听 `0.0.0.0`：

```powershell
python -m uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload
```

## 测试

测试会覆盖认证、跨用户隔离、会话恢复、长期记忆、标题修改、文档权限、PDF
页码与 Agent RAG 回答等流程。

```powershell
pytest -q
```

测试使用独立的随机用户和会话标识，运行前需保证测试配置中的 PostgreSQL 与模型
服务可用。

## 常用 Docker 命令

```powershell
# 查看状态
docker compose ps

# 查看后端与前端日志
docker compose logs -f backend frontend

# 重新构建并启动
docker compose up -d --build

# 停止服务，保留数据库数据
docker compose down

# 删除服务和数据库卷（会永久清空本项目数据）
docker compose down -v
```

## 答辩演示建议

1. 注册用户并进行一轮普通对话，展示流式 Markdown 回复。
2. 明确要求 Agent 记住一条信息，展示人在回路审批弹窗。
3. 新建会话后再次提问，展示长期记忆跨会话生效。
4. 发送一张图片并提问，展示图片压缩、上传和带图回答。
5. 在个人设置切换「Mock 离线模拟」，展示离线流式回答和「离线演示回答」标签，再切回真实模型。
6. 上传一份 PDF 或课件并提问，展示 RAG 检索和页码引用。
7. 打开历史会话，修改标题并继续对话。
8. 切换到另一个账号，展示会话、记忆和私有文档隔离。
9. 打开 Swagger，说明接口、SSE、数据库表和 Docker 服务结构。

答辩现场需要网络访问模型与 Embedding API；建议提前构建镜像、确认三个容器均为
`healthy`，并准备手机热点作为备用网络。

## 常见问题

### 页面能打开，但聊天或上传失败

检查模型密钥、网络和后端日志：

```powershell
docker compose logs --tail 100 backend
```

### 小程序 / App 提示「网络异常」

- uvicorn 必须监听 `0.0.0.0`，而不是默认的 `127.0.0.1`；
- `uniapp-frontend/ai-bot-uniapp/.env` 的 `VITE_API_BASE_URL` 必须是电脑的局域网 IP，不能写 `127.0.0.1`；
- 微信开发者工具需要勾选「不校验合法域名」，真机调试要求手机和电脑在同一网络。

### 图片发送失败

- 每轮最多 `MAX_IMAGES_PER_REQUEST`（默认 5）张，单会话最多 `MAX_IMAGES_PER_THREAD`（默认 20）张；
- 前端会先把图片压缩到长边 1280、JPEG 质量 0.8；原图过大时仍可能触发网络超时，可以继续调低压缩参数；
- 模型服务出错时，uni-app 前端会自动使用本地 Mock 回答，并显示「离线演示回答」标签。

### 修改 `JWT_SECRET_KEY` 后需要重新登录

这是预期行为。旧令牌由之前的密钥签发，修改密钥后无法再通过验证。

### 端口被占用

默认使用 `4173`、`8000`、`5432`。停止占用端口的本地服务，或修改
`docker-compose.yml` 左侧的宿主机端口。

### 数据库配置修改后无法启动

PostgreSQL 初始化参数只在数据卷首次创建时生效。开发阶段确认不需要旧数据后，可用
`docker compose down -v` 删除旧卷并重新启动。该命令会永久清空现有数据。

## 安全说明

- 不要提交 `.env`、API Key、JWT 密钥或数据库生产密码。
- 当前项目适合本地课程演示；部署到公网前应启用更严格的密钥管理、HTTPS、限流、
  上传安全检查、数据库备份和正式迁移方案。
- 前端使用 DOMPurify 清洗模型生成的 Markdown HTML，仍应避免信任未经审查的外部内容。
