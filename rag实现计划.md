# 学习助手 RAG 实现文档

> 本文档记录 **实现与设计**（非初始规划）。对外接口已独立到 `RAG接口文档.md`。
> 初始规划里想做的多解析器分层（`parsers/` + `schemas.py` + 全格式定位）已被砍掉，简化成单文件 loader，见第 7 节"与原规划的偏差"。

## 1. 功能概述

在上传文档上做检索增强：用户上传 PDF/TXT/MD/DOCX/PPTX → 解析成文本 → 切分 → 向量入库 → agent 通过 `search_knowledge_base` 工具检索并作答。

**两种可见范围**：
- `global`：全局知识库，所有用户可见（如教材），仅管理员可上传
- `private`：私有文档，仅上传者本人可见

**已实现的能力**：
- 5 种格式解析（PDF/TXT/MD/DOCX/PPTX）
- PDF 保留页码定位（`{"page_number": n}`），其余格式无定位
- 全局/私有权限隔离
- agent 自动判断何时检索、引用来源作答

## 2. 数据流

```
上传 (bytes)
   │
   ├─ loader.extract_segments(filename, data)     → list[(段文本, 定位|None)]
   │      PDF 按页分段（带页码），其余格式整段（定位 None）
   │
   ├─ splitter.split_segments(segments)           → list[(chunk文本, 定位|None)]
   │      段内切分（chunk_size=500, overlap=50），子块继承该段定位
   │
   ├─ embeddings.embed_documents(texts)           → list[向量(1024维)]
   │
   └─ ingest.ingest_file(...)                      → Document
          组装 Document + N 个 DocumentChunk，单事务提交

检索 (query)
   │
   └─ retrieval.search_knowledge(db, query, user_id)  → list[dict]
          向量检索 + scope 过滤（全局 OR 本人私有）+ 距离阈值 + top_k

agent
   └─ tools.rag_tools.search_knowledge_base(query)   ← 模型自主调用
```

函数签名、参数、返回结构见 `RAG接口文档.md` 第 4 节。

## 3. 数据模型（`app/models.py`）

两张表 + `users` 加 `is_admin` 列。

### `documents`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `title` | varchar(255) | 展示标题，默认取文件名 |
| `source` | varchar(512) | 原始文件名 |
| `file_type` | varchar(16) | pdf/txt/md/docx/pptx |
| `scope` | varchar(16) | `global` \| `private`，有索引 |
| `owner_id` | int FK→users.id | private 的归属者；global 为 NULL。删用户级联删 |
| `chunk_count` | int | chunk 数 |
| `created_at` | timestamptz | |

约束：`ck_documents_scope`（scope 取值）、`ck_documents_scope_owner`（global↔owner NULL、private↔owner NOT NULL）。

### `document_chunks`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `document_id` | int FK→documents.id | 有索引，删文档级联删 |
| `chunk_index` | int | 文档内序号 |
| `content` | text | chunk 文本 |
| `embedding` | vector(1024) | Qwen embedding |
| `scope` | varchar(16) | 反范式自 Document，检索免 join 做权限过滤 |
| `owner_id` | int\|null | 反范式；**普通列不设 FK** |
| `meta` | jsonb\|null | 定位信息，PDF 为 `{"page_number": n}`，其余 NULL |

约束：`uq_document_chunk_index`（document_id+chunk_index 唯一）、`ck_chunks_scope`、`ck_chunks_scope_owner`。
索引：`ix_chunks_embedding_hnsw`（HNSW + vector_cosine_ops）、`ix_chunks_scope_owner`。

> **为什么 scope/owner_id 反范式到 chunk**：检索时"全局 OR 本人私有"的判断直接在 chunk 表单表完成，不用 join documents。join 只用于取 title/source 展示，不参与权限。

### `users`（改动）
新增 `is_admin: bool`，`server_default=false`。管理员不靠用户名白名单（开放注册下可被抢注）。

## 4. 关键实现要点

**embedding 客户端共享**（`app/embeddings.py`）：`long_term.py` 里内联的 Qwen 客户端抽成 `get_embeddings()` 单例（`@lru_cache`），记忆检索 / ingestion / RAG 检索三处共用，维度常量 `EMBED_DIMS=1024` 也集中于此。

**PDF 按页分段**（`loader.py`）：`extract_segments` 对 PDF 返回**多段**（每页一段带 `page_number`），其余格式一段。返回多段是为了让切分在段内进行——这样 PDF 的 chunk 不跨页，页码天然正确。切分（`split_segments`）在每段内调 `RecursiveCharacterTextSplitter`，子块继承该段定位，输入输出同构 `list[tuple[str, dict|None]]`。

**单事务入库**（`ingest.py`）：`doc.chunks = [...]` 走 relationship，一次 `db.commit()`，失败整体回滚，不留半个文档。embedding 用 `embed_documents` **批量**一次调用，比逐条快。

**向量检索**（`retrieval.py`）：
- `cast(qvec, Vector(EMBED_DIMS))` —— **必须**。`embed_query` 返回 list，不 cast 则 psycopg 无法把它当 vector 传。
- `DocumentChunk.embedding.cosine_distance(...)` 生成 SQL `embedding <=> %(param)s`。
- 权限过滤：`scope=='global' OR (scope=='private' AND owner_id==user_id)`。`user_id` 来自调用方（工具里取自 runtime），**不是工具参数，模型无法伪造**。
- 阈值 `dist <= 0.6` 下推到 SQL；`order_by(dist)` 升序（距离小=相似）；`limit(top_k)`。

**Agent 集成**（`app/agent/bot.py`）：
- `BASE_PROMPT` 加了检索触发说明：用户问教材/课件/上传资料时**必须**调 `search_knowledge_base`，不得凭空编造；引用时若片段带页码应说明来源。
- 加了 `ToolCallLimitMiddleware(tool_name="search_knowledge_base", thread_limit=10, run_limit=3, exit_behavior="continue")`。
- 工具已注册进 `app/tools/__init__.py` 的 `tools` 列表；`api.py` 已 `include_router(documents.router)`。

**DB 初始化**（`app/db_init.py`）：`create_all` 前先 `CREATE EXTENSION IF NOT EXISTS vector`；另有 `_migrate_users_add_is_admin()` 幂等 ALTER，给老库补 `is_admin` 列（保数据，不 DROP 重建）。

## 5. 参数默认值
| 参数 | 值 | 位置 |
|---|---|---|
| chunk_size / overlap | 500 / 50 | `splitter.py` |
| RAG_TOP_K | 5 | `retrieval.py` |
| RAG_MIN_SCORE | 0.4 | `retrieval.py` |
| EMBED_DIMS | 1024 | `embeddings.py` |
| max_upload_bytes | 5MB | `config.py`（env `MAX_UPLOAD_BYTES` 可覆盖） |

> 实测相似度：相关项约 0.74~0.78，无关项低于 0.4。0.4 阈值余量充足，暂不用调。

## 6. 环境准备

```bash
pip install -e .                  # 新增依赖: langchain-text-splitters, python-docx, python-pptx
python -m app.db_init             # 建 vector 扩展 + 建表 + users 补 is_admin
```
设管理员（全局文档上传需 is_admin）：
```sql
UPDATE users SET is_admin=true WHERE username='你的账号';
```

## 7. 与原规划的偏差

| 原规划 | 实际 | 原因 |
|---|---|---|
| `parsers/` 5 个文件（协议+各格式） | 单个 `loader.py` 的 `extract_segments`（if/elif 分发） | 无 per-format 多态行为，一个函数够 |
| `schemas.py`（`ParsedDocument`/`ParsedSection`） | 删掉，用 `list[tuple[str, dict\|None]]` | 段结构简单到不需引入类 |
| 全格式定位（PPT 幻灯片号、DOCX 标题、TXT 行号） | 仅 PDF 页码 | 需求收敛为"PDF 顺带有页码"，其余无定位 |
| `service.py` / `vector_store.py` | **空文件**，未使用 | 早期骨架遗留，待删 |

## 8. 测试（`tests/test_rag.py`）

| 用例 | 验证 |
|---|---|
| `test_retrieval_hits_private_document` | 私有文档能被本人检索到 |
| `test_private_document_isolated_between_users` | A 的私有文档 B 检不到 |
| `test_global_document_visible_to_all` | 全局文档任意用户可见 |
| `test_pdf_chunk_carries_page_number` | PDF chunk 带页码 |
| `test_unsupported_format_rejected` | 415 |
| `test_empty_document_rejected` | 422 |
| `test_non_admin_cannot_upload_global` | 403 |
| `test_agent_retrieves_and_answers` | 端到端：agent 自动检索并引用（真实 LLM） |

conftest 新增 `upload` / `track_document` fixture；会话结束统一清理文档（global 不随用户级联删）。

运行：
```bash
python -m pytest tests/test_rag.py -v   # 8 项
python -m pytest -q                     # 全套（含 chat/auth）
```

## 9. 遗留 TODO

- 删除空文件 `app/rag/service.py`、`app/rag/vector_store.py`（骨架遗留，无引用）。
- （可选）其他格式定位：PPT 幻灯片号、DOCX 标题、TXT 行号——若需要，在对应 loader 分支返回 `meta` 即可，下游无需改。
- （可选）管理员初始化脚本：现在靠手动 SQL，可加 `app/seed_admin.py`。

## 10. 文件清单

创建：
```
app/embeddings.py
app/rag/__init__.py
app/rag/loader.py
app/rag/splitter.py
app/rag/ingest.py
app/rag/retrieval.py
app/tools/rag_tools.py
app/routers/documents.py
tests/test_rag.py
（app/rag/service.py、vector_store.py 为空文件，待删）
```
修改：
```
app/models.py            加 Document/DocumentChunk + User.is_admin
app/memory/long_term.py  改用共享 embedding 客户端
app/tools/__init__.py    注册 search_knowledge_base
app/api.py               注册 documents router
app/agent/bot.py         prompt + 限流
app/db_init.py           建 vector 扩展 + is_admin 迁移
app/config.py            加 max_upload_bytes
tests/conftest.py        upload/track_document fixture + 清理
pyproject.toml           加 3 个依赖
```

**相关文档**：`RAG接口文档.md`（对外接口）、`记忆系统文档.md`（短期/长期记忆、分层与 LRU 治理）、`文档.md`（项目一期结构说明）。
