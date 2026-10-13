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
- **流式输出**：通过 SSE 将 Agent 回复实时推送到网页端。
- **会话管理**：查看、恢复、重命名和删除历史会话。
- **Docker 部署**：前端、后端和 pgvector 数据库可通过 Docker Compose 一键启动。

## 系统架构

```mermaid
flowchart LR
    U[浏览器] --> F[前端与 API 代理<br/>:4173]
    F -->|/api| B[FastAPI 后端<br/>:8000]
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
| 前端 | HTML、CSS、原生 JavaScript、Marked、DOMPurify |
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
├── web/
│   ├── assets/             # 头像与前端依赖
│   ├── dev_server.py       # 静态页面服务与同源 API 代理
│   └── index.html          # 网页端应用
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
| 网页端 | <http://127.0.0.1:4173> |
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
| `DASHSCOPE_API_KEY` | 是 | Qwen Embedding 密钥 |
| `DASHSCOPE_BASE_URL` | 否 | DashScope OpenAI-compatible 地址 |
| `ZHIPUAI_API_KEY` | 否 | 联网搜索密钥；不配置时网页搜索工具不可用 |
| `JWT_SECRET_KEY` | 是 | JWT 签名密钥，建议至少 32 个字符 |
| `MAX_UPLOAD_BYTES` | 否 | 单文件上传上限，默认 `5MB` |
| `POSTGRES_DB` | 否 | 默认 `ai_bot` |
| `POSTGRES_USER` | 否 | 默认 `ai_bot` |
| `POSTGRES_PASSWORD` | 否 | 默认 `ai_bot_password`，非本地环境请修改 |

Compose 会根据 PostgreSQL 配置自动生成容器内 `DATABASE_URL`，无需在 `.env`
里写 `localhost` 数据库地址。

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
| `GET` | `/conversations` | 会话列表 |
| `GET` | `/conversations/{thread_id}` | 会话详情与待审批状态 |
| `PATCH` | `/conversations/{thread_id}` | 修改会话标题 |
| `DELETE` | `/conversations/{thread_id}` | 删除会话及其 Checkpoint |
| `POST` | `/documents` | 上传并向量化文档 |
| `GET` | `/documents` | 获取当前用户可见文档 |
| `DELETE` | `/documents/{doc_id}` | 删除有权限操作的文档 |

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
4. 上传一份 PDF 或课件并提问，展示 RAG 检索和页码引用。
5. 打开历史会话，修改标题并继续对话。
6. 切换到另一个账号，展示会话、记忆和私有文档隔离。
7. 打开 Swagger，说明接口、SSE、数据库表和 Docker 服务结构。

答辩现场需要网络访问模型与 Embedding API；建议提前构建镜像、确认三个容器均为
`healthy`，并准备手机热点作为备用网络。

## 常见问题

### 页面能打开，但聊天或上传失败

检查模型密钥、网络和后端日志：

```powershell
docker compose logs --tail 100 backend
```

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
