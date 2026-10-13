# RAG 接口文档

> 学习助手 RAG 功能的对外接口。实现细节与设计见 `rag实现计划.md`。
> 面向：调用方（前端/脚本）、二次开发者。

## 1. RAG 是什么

用户上传文档（PDF/TXT/MD/DOCX/PPTX）→ 系统解析切分向量入库 → 聊天时 agent 自动检索相关内容并作答。

- **global 文档**：全局知识库，所有用户可见（如教材）。仅管理员可上传。
- **private 文档**：私有文档，仅上传者本人可见。

## 2. HTTP API

前缀 `/documents`。**全部需鉴权**：请求头 `Authorization: Bearer <JWT>`。

### 2.1 上传文档 `POST /documents`

`multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 上传文件，支持 .pdf/.txt/.md/.docx/.pptx |
| `scope` | text | 否 | `global` 或 `private`，默认 `private` |
| `title` | text | 否 | 展示标题，默认取文件名 |

**成功 `200`**：
```json
{
  "id": 1,
  "title": "note.txt",
  "source": "note.txt",
  "file_type": "txt",
  "scope": "private",
  "owner_id": 3,
  "chunk_count": 2,
  "created_at": "2026-10-13T12:00:00+00:00"
}
```

**错误**：
| 码 | 场景 | detail 示例 |
|---|---|---|
| 403 | 非管理员上传 global | `只有管理员可以上传全局文档` |
| 413 | 超过 5MB（可配 `MAX_UPLOAD_BYTES`） | `文件超过上限 5MB` |
| 415 | 不支持的格式 | `不支持的文件格式：xlsx` |
| 422 | 无有效文本（如扫描件 PDF） | `「x.pdf」没有解析出可用文本` |

**curl 示例**：
```bash
curl -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@book.pdf" \
  -F "scope=global" \
  -F "title=物理教材"
```

### 2.2 列出文档 `GET /documents`

返回当前用户可见的文档：**所有 global + 自己的 private**，按创建时间倒序。

**成功 `200`**：`DocumentOut` 数组（字段同 2.1 的成功响应）。

### 2.3 删除文档 `DELETE /documents/{doc_id}`

**成功 `204`**（无 body），chunk 一并删除。

**错误**：
| 码 | 场景 |
|---|---|
| 404 | 文档不存在 |
| 403 | 非本人删 private / 非管理员删 global |

## 3. Agent 接口（聊天侧）

检索通过 agent 的工具自动触发，**调用方无需显式检索**。用户正常发消息即可：

```
POST /chat   { "message": "根据我上传的文档，XXX 是什么？", "thread_id": "t1" }
```

agent 会自行判断是否调用 `search_knowledge_base`，并在回答中引用文档内容（PDF 会带页码）。

> 触发条件：用户询问教材、课件、上传文档、课程资料相关内容时，模型**必须**调用检索工具；不编造知识库内容。

## 4. Python 接口（内部模块）

供二次开发直接调用，路径在 `app/` 下。

### 4.1 `app.rag.loader.extract_segments`
```python
def extract_segments(filename: str, data: bytes) -> list[tuple[str, dict | None]]
```
按扩展名把文件字节转成 `(文本, 定位)` 段列表。
- PDF → 每页一段，定位 `{"page_number": n}`
- txt/md/docx/pptx → 整段，定位 `None`
- 不支持的后缀抛 `UnsupportedFormatError`

### 4.2 `app.rag.splitter.split_segments`
```python
def split_segments(segments: list[tuple[str, dict | None]]) -> list[tuple[str, dict | None]]
```
每段内切分（chunk_size=500, overlap=50），子块继承该段定位。输入输出同构。

### 4.3 `app.rag.ingest.ingest_file`
```python
def ingest_file(
    db, *, filename: str, data: bytes,
    scope: str, owner_id: int | None, title: str | None = None,
) -> Document
```
生成一段完整入库流程：解析 → 切分 → 批量 embed → 建 Document + chunks（单事务）。无文本抛 `EmptyDocumentError`。
`scope`/`owner_id` 由调用方决定，本函数不判权限。

### 4.4 `app.rag.retrieval.search_knowledge`
```python
def search_knowledge(db, *, query: str, user_id: int, top_k: int = 5) -> list[dict]
```
向量检索 + 权限过滤，返回按相似度降序的片段列表（无命中为 `[]`）。每项：
```python
{
    "document_id": int,
    "title": str,
    "source": str,
    "file_type": str,
    "content": str,          # chunk 文本
    "locator": dict,         # 定位，PDF 为 {"page_number": n}，其余为 {}
    "similarity": float,     # 0~1，越大越相关
}
```
权限规则：命中 `scope=='global'` 或 `scope=='private' 且 owner_id==user_id` 的 chunk。

### 4.5 `app.tools.rag_tools.search_knowledge_base`（LangChain 工具）
```python
@tool
def search_knowledge_base(query: str, runtime: ToolRuntime) -> str
```
暴露给模型的参数只有 `query`；`user_id` 从 `runtime.context.user_id` 取（模型无法伪造）。无命中返回 `"知识库中没有检索到相关内容。"`，否则返回 JSON 字符串。

## 5. 配置项

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `MAX_UPLOAD_BYTES` | 5242880（5MB） | 单文件上传上限 |

代码内常量：
| 常量 | 值 | 位置 |
|---|---|---|
| chunk_size / overlap | 500 / 50 | `app/rag/splitter.py` |
| RAG_TOP_K | 5 | `app/rag/retrieval.py` |
| RAG_MIN_SCORE | 0.4 | `app/rag/retrieval.py` |
| EMBED_DIMS | 1024 | `app/embeddings.py` |

## 6. 权限与错误一览

| 操作 | 允许者 |
|---|---|
| 上传 global | 管理员（`users.is_admin=true`） |
| 上传 private | 任意登录用户（归属本人） |
| 查看 | 全局文档所有用户；私有文档仅本人 |
| 删除 global | 管理员 |
| 删除 private | 本人 |

| HTTP 码 | 含义 |
|---|---|
| 403 | 权限不足 |
| 404 | 文档不存在 |
| 413 | 文件过大 |
| 415 | 格式不支持 |
| 422 | 无有效文本 |
