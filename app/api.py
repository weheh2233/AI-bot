import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.bot import MAIN_MODEL_NODE, AgentContext, get_agent
from app.auth import get_current_user
from app.database import get_db
from app.memory.long_term import store_context
from app.memory.short_term import checkpointer_context
from app.models import Conversation, User
from app.routers import auth, documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 连接池在应用启动时建立，关闭时释放，绝不能放在请求里
    with checkpointer_context() as checkpointer, store_context() as store:
        app.state.agent = get_agent(checkpointer, store)
        yield


app = FastAPI(title="AI-bot", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(documents.router)


class ChatRequest(BaseModel):
    message: str
    thread_id: str


class ResumeRequest(BaseModel):
    thread_id: str
    decisions: list[dict]


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime | None = None
    elapsed: float | None = None


class ConversationSummary(BaseModel):
    thread_id: str
    title: str
    preview: str
    message_count: int
    updated_at: datetime
    awaiting_approval: bool


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]
    action_requests: list[dict] = Field(default_factory=list)
    review_configs: list[dict] = Field(default_factory=list)


class ConversationTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationTitle(BaseModel):
    thread_id: str
    title: str


def _config(user: User, thread_id: str) -> dict:
    # 会话隔离：checkpointer 只按 thread_id 隔离，不认用户。若直接用客户端传来的
    # thread_id，任何人传相同值即可读到他人会话历史。这里用 user_id 前缀绑定，
    # 让不同用户的同名 thread_id 落到不同的实际存储键。
    return {"configurable": {"thread_id": f"user-{user.id}:{thread_id}"}}


def _context(user: User) -> AgentContext:
    return AgentContext(user_id=str(user.id))


def _interrupt_payload(result: dict) -> dict | None:
    """从 invoke 结果中提取待审批请求；命中中断返回响应体，否则返回 None。"""
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    value = interrupts[0].value
    return {
        "status": "awaiting_approval",
        "action_requests": value["action_requests"],
        "review_configs": value["review_configs"],
    }


def _snapshot_interrupt_payload(snapshot) -> dict | None:
    """从已持久化的 Agent 状态中提取尚未处理的人工审批。"""
    for task in snapshot.tasks:
        if task.interrupts:
            value = task.interrupts[0].value
            return {
                "status": "awaiting_approval",
                "action_requests": value["action_requests"],
                "review_configs": value["review_configs"],
            }
    return None


def _content_text(content) -> str:
    """把 LangChain 的字符串或内容块转换成适合历史记录展示的纯文本。"""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts).strip()


def _conversation_messages(
    snapshot, timestamp: datetime | None = None
) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []
    for message in snapshot.values.get("messages", []):
        if isinstance(message, HumanMessage):
            # SummarizationMiddleware 把摘要以 HumanMessage 形式插进历史，它不是用户
            # 说的话，不能出现在会话记录里。
            if message.additional_kwargs.get("lc_source") == "summarization":
                continue
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            continue

        content = _content_text(message.content)
        if content:
            stored_timestamp = message.additional_kwargs.get("timestamp", timestamp)
            stored_elapsed = message.additional_kwargs.get("elapsed")
            messages.append(
                ConversationMessage(
                    role=role,
                    content=content,
                    timestamp=stored_timestamp,
                    elapsed=stored_elapsed if role == "assistant" else None,
                )
            )
    return messages


def _timed_user_message(content: str) -> HumanMessage:
    return HumanMessage(
        content=content,
        additional_kwargs={"timestamp": datetime.now(timezone.utc).isoformat()},
    )


def _store_assistant_timing(agent, config: dict, elapsed: float) -> None:
    """Replace the latest assistant message with timing metadata in the checkpoint."""
    snapshot = agent.get_state(config)
    for message in reversed(snapshot.values.get("messages", [])):
        if not isinstance(message, AIMessage) or not _content_text(message.content):
            continue
        metadata = {
            **message.additional_kwargs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed": elapsed,
        }
        agent.update_state(
            config,
            {"messages": [message.model_copy(update={"additional_kwargs": metadata})]},
        )
        return


def _short_text(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else f"{value[:limit]}…"


def _conversation_summary(
    thread_id: str,
    updated_at: datetime,
    snapshot,
    title: str,
) -> ConversationSummary:
    messages = _conversation_messages(snapshot)
    preview = messages[-1].content if messages else "这个会话还没有可展示的消息"
    return ConversationSummary(
        thread_id=thread_id,
        title=title,
        preview=_short_text(preview, 80),
        message_count=len(messages),
        updated_at=updated_at,
        awaiting_approval=_snapshot_interrupt_payload(snapshot) is not None,
    )


def _derive_title(messages: list[ConversationMessage]) -> str | None:
    first_user = next((item.content for item in messages if item.role == "user"), "")
    return _short_text(first_user, 36) or None


def _fixed_title(db: Session, thread_id: str, internal_thread_id: str, owner_id: int,
                 snapshot) -> str:
    """返回会话标题，首次出现用户消息时派生并落库固定。

    之后只读不再改写，避免历史压缩把首条用户消息挤出 state 后标题漂移。
    thread_id 是去前缀的对外 id，用于返回；internal 是带用户前缀的存储 id。
    """
    row = db.execute(
        select(Conversation).where(Conversation.thread_id == internal_thread_id)
    ).scalar_one_or_none()
    if row is not None:
        return row.title

    title = _derive_title(_conversation_messages(snapshot))
    if title is None:
        # 还没有用户消息（例如仅存在中断），此时不固定标题，等有消息再定
        return "新会话"
    db.add(Conversation(thread_id=internal_thread_id, owner_id=owner_id, title=title))
    try:
        db.commit()
    except IntegrityError:
        # 并发下另一个请求已插入同一会话，回滚后读回既有标题
        db.rollback()
        return db.execute(
            select(Conversation.title).where(Conversation.thread_id == internal_thread_id)
        ).scalar_one()
    return title


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户有 checkpoint 的会话，最近更新的排在前面。"""
    internal_prefix = f"user-{current.id}:"
    rows = db.execute(
        text(
            """
            SELECT thread_id, updated_at
            FROM (
                SELECT DISTINCT ON (thread_id)
                    thread_id,
                    CAST(checkpoint ->> 'ts' AS timestamptz) AS updated_at
                FROM checkpoints
                WHERE thread_id LIKE :thread_pattern
                  AND checkpoint_ns = ''
                ORDER BY thread_id, checkpoint_id DESC
            ) AS latest
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        ),
        {"thread_pattern": f"{internal_prefix}%", "limit": limit},
    ).all()

    conversations: list[ConversationSummary] = []
    for internal_thread_id, updated_at in rows:
        thread_id = internal_thread_id.removeprefix(internal_prefix)
        snapshot = request.app.state.agent.get_state(_config(current, thread_id))
        title = _fixed_title(db, thread_id, internal_thread_id, current.id, snapshot)
        conversations.append(
            _conversation_summary(thread_id, updated_at, snapshot, title)
        )
    return conversations


@app.get("/conversations/{thread_id}", response_model=ConversationDetail)
def get_conversation(
    thread_id: str,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取当前用户的一条会话；客户端只能使用去掉用户前缀的 thread_id。"""
    internal_thread_id = _config(current, thread_id)["configurable"]["thread_id"]
    updated_at = db.execute(
        text(
            """
            SELECT CAST(checkpoint ->> 'ts' AS timestamptz)
            FROM checkpoints
            WHERE thread_id = :thread_id
              AND checkpoint_ns = ''
            ORDER BY checkpoint_id DESC
            LIMIT 1
            """
        ),
        {"thread_id": internal_thread_id},
    ).scalar_one_or_none()
    if updated_at is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    snapshot = request.app.state.agent.get_state(_config(current, thread_id))
    title = _fixed_title(db, thread_id, internal_thread_id, current.id, snapshot)
    summary = _conversation_summary(thread_id, updated_at, snapshot, title)
    pending = _snapshot_interrupt_payload(snapshot) or {}
    return ConversationDetail(
        **summary.model_dump(),
        # 新消息从 additional_kwargs 读取逐条时间；旧 checkpoint 没有该字段时，
        # 回退到会话最新 checkpoint 时间，兼容已有历史数据。
        messages=_conversation_messages(snapshot, timestamp=updated_at),
        action_requests=pending.get("action_requests", []),
        review_configs=pending.get("review_configs", []),
    )


@app.patch("/conversations/{thread_id}", response_model=ConversationTitle)
def update_conversation_title(
    thread_id: str,
    payload: ConversationTitleUpdate,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改当前用户的一条会话标题；不改变 checkpoint 或消息内容。"""
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="会话标题不能为空")

    internal_thread_id = _config(current, thread_id)["configurable"]["thread_id"]
    conversation = db.execute(
        select(Conversation).where(
            Conversation.thread_id == internal_thread_id,
            Conversation.owner_id == current.id,
        )
    ).scalar_one_or_none()
    if conversation is None:
        checkpoint_exists = db.execute(
            text(
                """
                SELECT 1
                FROM checkpoints
                WHERE thread_id = :thread_id AND checkpoint_ns = ''
                LIMIT 1
                """
            ),
            {"thread_id": internal_thread_id},
        ).scalar_one_or_none()
        if checkpoint_exists is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        snapshot = request.app.state.agent.get_state(_config(current, thread_id))
        _fixed_title(db, thread_id, internal_thread_id, current.id, snapshot)
        conversation = db.execute(
            select(Conversation).where(
                Conversation.thread_id == internal_thread_id,
                Conversation.owner_id == current.id,
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=404, detail="会话不存在")

    conversation.title = title
    db.commit()
    return ConversationTitle(thread_id=thread_id, title=title)


@app.delete("/conversations/{thread_id}", status_code=204)
def delete_conversation(
    thread_id: str,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除当前用户的一条会话（清空其全部 checkpoint）。"""
    internal_thread_id = _config(current, thread_id)["configurable"]["thread_id"]
    # 用户前缀绑定 thread_id，因此这里天然只能命中当前用户的会话。
    exists = db.execute(
        text(
            """
            SELECT 1 FROM checkpoints
            WHERE thread_id = :thread_id AND checkpoint_ns = ''
            LIMIT 1
            """
        ),
        {"thread_id": internal_thread_id},
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    request.app.state.agent.checkpointer.delete_thread(internal_thread_id)
    # 会话元数据（固定标题）随会话一并清除
    db.execute(
        text("DELETE FROM conversations WHERE thread_id = :thread_id"),
        {"thread_id": internal_thread_id},
    )
    db.commit()


@app.post("/chat")
def chat(
    req: ChatRequest,
    request: Request,
    current: User = Depends(get_current_user),
):
    payload = {"messages": [_timed_user_message(req.message)]}
    config = _config(current, req.thread_id)
    start_time = time.perf_counter()
    result = request.app.state.agent.invoke(payload, config, context=_context(current))

    pending = _interrupt_payload(result)
    if pending:
        # 命中人工审批：不是错误，但本轮没有最终回复，用 202 与正常完成区分
        return JSONResponse(pending, status_code=202)
    elapsed = round(time.perf_counter() - start_time, 2)
    _store_assistant_timing(request.app.state.agent, config, elapsed)
    return {"reply": result["messages"][-1].content, "elapsed": elapsed}


@app.post("/chat/resume")
def chat_resume(
    req: ResumeRequest,
    request: Request,
    current: User = Depends(get_current_user),
):
    config = _config(current, req.thread_id)
    start_time = time.perf_counter()
    result = request.app.state.agent.invoke(
        Command(resume={"decisions": req.decisions}),
        config,
        context=_context(current),
    )

    pending = _interrupt_payload(result)
    if pending:
        # 一轮可能有多个工具调用待审批，全部决策完才会继续
        return JSONResponse(pending, status_code=202)
    elapsed = round(time.perf_counter() - start_time, 2)
    _store_assistant_timing(request.app.state.agent, config, elapsed)
    return {"reply": result["messages"][-1].content, "elapsed": elapsed}


@app.post("/chat/stream")
def chat_stream(
    req: ChatRequest,
    request: Request,
    current: User = Depends(get_current_user),
):
    agent = request.app.state.agent
    payload = {"messages": [_timed_user_message(req.message)]}
    config = _config(current, req.thread_id)
    context = _context(current)

    def event_gen():
        start_time = time.perf_counter()
        interrupted = False
        for chunk, meta in agent.stream(
            payload, config, context=context, stream_mode="messages"
        ):
            # 只转发主模型节点的文本。中间件（如摘要）会借别的节点发起内部模型调用，
            # 那些输出不该进入对话；ToolMessage 是工具原始返回（RAG 片段 / 网页 HTML），
            # 同属内部数据，一并挡掉。
            if isinstance(meta, dict) and meta.get("langgraph_node") != MAIN_MODEL_NODE:
                continue
            if isinstance(chunk, ToolMessage):
                continue
            if chunk.content:
                data = json.dumps({"delta": chunk.content}, ensure_ascii=False)
                yield f"data: {data}\n\n"

        # messages 模式不会吐中断事件，流跑完后回查状态确认是否挂起等审批
        state = agent.get_state(config)
        for task in state.tasks:
            if task.interrupts:
                value = task.interrupts[0].value
                pending = {
                    "status": "awaiting_approval",
                    "action_requests": value["action_requests"],
                    "review_configs": value["review_configs"],
                }
                #整段 event_gen 里的每个 yield 语句就是在发 SSE。
                # 加上 media_type="text/event-stream" 这个声明，FastAPI 就知道"我返回的是一串 SSE 事件流"。
                #yield就是返回一个值然后暂停加断点，下次能从暂停处继续，不像return返回一个值就结束
                yield f"data: {json.dumps(pending, ensure_ascii=False)}\n\n"
                interrupted = True
                break

        elapsed = round(time.perf_counter() - start_time, 2)
        if not interrupted:
            _store_assistant_timing(agent, config, elapsed)
        yield f"data: {{\"type\": \"done\", \"elapsed\": {elapsed}}}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
