import json
import time
import unicodedata
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.bot import MAIN_MODEL_NODE, AgentContext, get_agent
from app.auth import get_current_user
from app.chat_streams import (
    CANCELLED_EVENT,
    STREAM_REPLAY_INTERVAL,
    ChatRun,
    ChatStreamRegistry,
)
from app.conversation_search import sync_title_terms, title_terms
from app.database import get_db
from app.memory.long_term import store_context
from app.memory.short_term import async_checkpointer_context, checkpointer_context
from app.models import Conversation, ConversationSearchTerm, Persona, User
from app.routers import auth, documents, settings as settings_router
from app.model_settings import (
    agent_for_connection, load_connection, mark_used, model_error_message,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 连接池在应用启动时建立，关闭时释放，绝不能放在请求里
    with checkpointer_context() as checkpointer, store_context() as store:
        async with async_checkpointer_context() as async_checkpointer:
            # 注册同步连接saver的agent和异步saver的agent
            app.state.agent = get_agent(checkpointer, store)
            app.state.async_agent = get_agent(async_checkpointer, store, async_mode=True)
            yield
#yield下没内容了代表：这个生命周期没有对于关闭客户端之后的处理

app = FastAPI(title="AI-bot", lifespan=lifespan)
app.state.chat_streams = ChatStreamRegistry()
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(settings_router.router)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, exc: RequestValidationError):
    # 默认 422 会带 input；设置页包含 Key/密码，不能原样回显请求体。
    errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
              for error in exc.errors()]
    return JSONResponse({"detail": "请求参数不正确，请检查字段内容", "errors": errors}, 422)


class ChatRequest(BaseModel):
    message: str
    thread_id: str
    persona_id: int | None = None
    turn_id: str | None = None
    regenerate: bool = False


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
    is_favorite: bool = False
    tags: list[str] = Field(default_factory=list)


class ConversationSearchResult(BaseModel):
    thread_id: str
    title: str
    preview: str
    message_count: int
    updated_at: datetime
    awaiting_approval: bool
    is_favorite: bool
    tags: list[str]


class ConversationMetadataUpdate(BaseModel):
    is_favorite: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=8)


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage]
    action_requests: list[dict] = Field(default_factory=list)
    review_configs: list[dict] = Field(default_factory=list)


class ConversationTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationTitle(BaseModel):
    thread_id: str
    title: str


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role_definition: str = Field(min_length=1, max_length=4000)
    tone: str = Field(min_length=1, max_length=4000)
    style_rules: str = Field(default="", max_length=4000)
    constraints: str = Field(default="", max_length=4000)


class PersonaUpdate(PersonaCreate):
    pass


class PersonaOut(PersonaCreate):
    id: int | None
    owner_id: int | None
    version: int
    is_system: bool

    class Config:
        from_attributes = True


class DefaultPersonaUpdate(BaseModel):
    persona_id: int | None = None


class ConversationPersonaUpdate(BaseModel):
    persona_id: int


def _config(
    user: User,
    thread_id: str,
    *,
    run_name: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    # 会话隔离：checkpointer 只按 thread_id 隔离，不认用户。若直接用客户端传来的
    # thread_id，任何人传相同值即可读到他人会话历史。这里用 user_id 前缀绑定，
    # 让不同用户的同名 thread_id 落到不同的实际存储键。
    internal_thread_id = f"user-{user.id}:{thread_id}"
    config = {
        "configurable": {"thread_id": internal_thread_id},
        # LangSmith 用这个字段把同一会话的多轮 trace 聚合到一个 Thread 中。
        # 只发送数据库用户 ID 和内部会话 ID，不发送用户名、JWT 或 API Key。
        "metadata": {
            "thread_id": internal_thread_id,
            "user_id": str(user.id),
        },
    }
    if run_name:
        config["run_name"] = run_name
    if tags:
        config["tags"] = tags
    return config


def _context(user: User) -> AgentContext:
    return AgentContext(user_id=str(user.id))


def _persona_prompt(persona: Persona) -> str:
    fields = [
        f"角色定位：{persona.role_definition.strip()}",
        f"语气：{persona.tone.strip()}",
    ]
    if persona.style_rules.strip():
        fields.append(f"回答风格：{persona.style_rules.strip()}")
    if persona.constraints.strip():
        fields.append(f"行为边界：{persona.constraints.strip()}")
    return "\n".join(fields)


def _persona_snapshot(persona: Persona) -> dict:
    return {
        "id": persona.id,
        "owner_id": persona.owner_id,
        "name": persona.name,
        "role_definition": persona.role_definition,
        "tone": persona.tone,
        "style_rules": persona.style_rules,
        "constraints": persona.constraints,
        "prompt": _persona_prompt(persona),
        "version": persona.version,
        "is_system": persona.is_system,
    }


def _system_persona(db: Session) -> Persona:
    persona = db.execute(
        select(Persona).where(Persona.is_system.is_(True), Persona.name == "昔涟")
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=500, detail="系统默认角色未初始化")
    return persona


def _visible_persona(db: Session, user: User, persona_id: int) -> Persona:
    persona = db.execute(
        select(Persona).where(
            Persona.id == persona_id,
            (Persona.is_system.is_(True)) | (Persona.owner_id == user.id),
        )
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=404, detail="角色不存在或无权使用")
    return persona


def _persona_for_thread(
    db: Session, user: User, thread_id: str, preferred_persona_id: int | None = None
) -> tuple[str, str]:
    """读取会话快照；新会话回退到用户默认角色或系统角色。"""
    internal_thread_id = _config(user, thread_id)["configurable"]["thread_id"]
    row = db.execute(
        select(Conversation).where(Conversation.thread_id == internal_thread_id)
    ).scalar_one_or_none()
    if row is not None and row.persona_snapshot:
        snapshot = row.persona_snapshot
        return str(snapshot.get("name", "昔涟")), str(snapshot.get("prompt", ""))

    if row is not None and row.persona_id is not None:
        persona = _visible_persona(db, user, row.persona_id)
    else:
        persona = _visible_persona(db, user, preferred_persona_id) if preferred_persona_id else None
    if persona is None and user.default_persona_id is not None:
        persona = _visible_persona(db, user, user.default_persona_id)
    if persona is None:
        persona = _system_persona(db)
    return persona.name, _persona_prompt(persona)


def _context_for_thread(
    db: Session, user: User, thread_id: str, preferred_persona_id: int | None = None
) -> AgentContext:
    name, prompt = _persona_for_thread(db, user, thread_id, preferred_persona_id)
    return AgentContext(user_id=str(user.id), persona_name=name, persona_prompt=prompt)


def _bind_persona_after_chat(
    db: Session,
    user: User,
    thread_id: str,
    state_snapshot=None,
    preferred_persona_id: int | None = None,
) -> None:
    """首次产生会话后固定角色快照；已有快照不被角色表更新覆盖。"""
    internal_thread_id = _config(user, thread_id)["configurable"]["thread_id"]
    row = db.execute(
        select(Conversation).where(Conversation.thread_id == internal_thread_id)
    ).scalar_one_or_none()
    if row is not None and row.persona_snapshot:
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return
    persona = None
    if row is not None and row.persona_id is not None:
        persona = _visible_persona(db, user, row.persona_id)
    elif preferred_persona_id is not None:
        persona = _visible_persona(db, user, preferred_persona_id)
    if persona is None:
        if user.default_persona_id is not None:
            persona = _visible_persona(db, user, user.default_persona_id)
        if persona is None:
            persona = _system_persona(db)
    persona_snapshot = _persona_snapshot(persona)
    if row is None:
        row = Conversation(
            thread_id=internal_thread_id,
            owner_id=user.id,
            title=(
                _derive_title(_conversation_messages(state_snapshot))
                if state_snapshot is not None else "新会话"
            ),
            persona_id=persona.id,
            persona_version=persona.version,
            persona_snapshot=persona_snapshot,
        )
        db.add(row)
    else:
        if row.title == "新会话" and state_snapshot is not None:
            row.title = _derive_title(_conversation_messages(state_snapshot)) or row.title
        row.persona_id = persona.id
        row.persona_version = persona.version
        row.persona_snapshot = persona_snapshot
    db.commit()


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


async def _store_assistant_timing(agent, config: dict, elapsed: float) -> None:
    """Replace the latest assistant message with timing metadata in the checkpoint."""
    snapshot = await agent.aget_state(config)
    for message in reversed(snapshot.values.get("messages", [])):
        if not isinstance(message, AIMessage) or not _content_text(message.content):
            continue
        metadata = {
            **message.additional_kwargs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed": elapsed,
        }
        await agent.aupdate_state(
            config,
            {"messages": [message.model_copy(update={"additional_kwargs": metadata})]},
        )
        return


async def _prepare_regeneration(agent, config: dict) -> str:
    """Remove the most recent user turn from the checkpoint and return its text."""
    snapshot = await agent.aget_state(config)
    messages = list(snapshot.values.get("messages", []))
    user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
            and messages[index].additional_kwargs.get("lc_source") != "summarization"
        ),
        None,
    )
    if user_index is None:
        raise HTTPException(status_code=409, detail="没有可重新生成的用户消息")

    turn_messages = messages[user_index:]
    if not any(isinstance(message, AIMessage) for message in turn_messages[1:]):
        raise HTTPException(status_code=409, detail="最近一轮还没有完成回复")
    if any(
        (isinstance(message, ToolMessage) and message.name == "save_user_memory")
        or (
            isinstance(message, AIMessage)
            and any(call.get("name") == "save_user_memory" for call in message.tool_calls)
        )
        for message in turn_messages
    ):
        raise HTTPException(
            status_code=409,
            detail="最近一轮已执行长期记忆写入，暂不支持重新生成以避免重复副作用",
        )
    if any(not message.id for message in turn_messages):
        raise HTTPException(status_code=409, detail="最近一轮消息缺少 checkpoint 标识")

    original_text = _content_text(messages[user_index].content)
    await agent.aupdate_state(
        config,
        {"messages": [RemoveMessage(id=message.id) for message in turn_messages]},#直接让langgraph删近这几条消息
    )
    return original_text


def _short_text(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else f"{value[:limit]}…"


def _conversation_summary(
    thread_id: str,
    updated_at: datetime,
    snapshot,
    title: str,
    conversation: Conversation | None = None,
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
        is_favorite=conversation.is_favorite if conversation is not None else False,
        tags=(conversation.tags or []) if conversation is not None else [],
    )


def _derive_title(messages: list[ConversationMessage]) -> str | None:
    first_user = next((item.content for item in messages if item.role == "user"), "")
    return _short_text(first_user, 36) or None


def _fixed_title(db: Session, thread_id: str, internal_thread_id: str, owner_id: int,
                 snapshot) -> Conversation | None:
    """返回会话标题，首次出现用户消息时派生并落库固定。

    之后只读不再改写，避免历史压缩把首条用户消息挤出 state 后标题漂移。
    thread_id 是去前缀的对外 id，用于返回；internal 是带用户前缀的存储 id。
    """
    row = db.execute(
        select(Conversation).where(Conversation.thread_id == internal_thread_id)
    ).scalar_one_or_none()
    if row is not None:
        if sync_title_terms(db, row):
            db.commit()
        return row

    title = _derive_title(_conversation_messages(snapshot))
    if title is None:
        # 还没有用户消息（例如仅存在中断），此时不固定标题，等有消息再定
        return None
    row = Conversation(thread_id=internal_thread_id, owner_id=owner_id, title=title)
    db.add(row)
    try:
        db.flush()
        sync_title_terms(db, row)
        db.commit()
    except IntegrityError:
        # 并发下另一个请求已插入同一会话，回滚后读回既有标题
        db.rollback()
        row = db.execute(
            select(Conversation).where(Conversation.thread_id == internal_thread_id)
        ).scalar_one()
        if sync_title_terms(db, row):
            db.commit()
    return row


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/personas", response_model=list[PersonaOut])
def list_personas(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出系统预设和当前用户自己的角色。"""
    return db.execute(
        select(Persona).where(
            (Persona.is_system.is_(True)) | (Persona.owner_id == current.id)
        ).order_by(Persona.is_system.desc(), Persona.updated_at.desc(), Persona.id)
    ).scalars().all()


@app.post("/personas", response_model=PersonaOut, status_code=201)
def create_persona(
    payload: PersonaCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = Persona(owner_id=current.id, **payload.model_dump())
    db.add(persona)
    db.commit()
    db.refresh(persona)
    return persona


@app.patch("/personas/{persona_id}", response_model=PersonaOut)
def update_persona(
    persona_id: int,
    payload: PersonaUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = db.execute(
        select(Persona).where(Persona.id == persona_id, Persona.owner_id == current.id)
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=404, detail="角色不存在或不可修改")
    for key, value in payload.model_dump().items():
        setattr(persona, key, value)
    persona.version += 1
    db.commit()
    db.refresh(persona)
    return persona


@app.delete("/personas/{persona_id}", status_code=204)
def delete_persona(
    persona_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = db.execute(
        select(Persona).where(Persona.id == persona_id, Persona.owner_id == current.id)
    ).scalar_one_or_none()
    if persona is None:
        raise HTTPException(status_code=404, detail="角色不存在或不可删除")
    if current.default_persona_id == persona.id:
        current.default_persona_id = None
    db.delete(persona)
    db.commit()


@app.patch("/users/me/default-persona", response_model=PersonaOut | None)
def update_default_persona(
    payload: DefaultPersonaUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.persona_id is None:
        current.default_persona_id = None
        db.commit()
        return None
    persona = _visible_persona(db, current, payload.persona_id)
    current.default_persona_id = persona.id
    db.commit()
    return persona


@app.get("/users/me/default-persona", response_model=PersonaOut)
def get_default_persona(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current.default_persona_id is not None:
        return _visible_persona(db, current, current.default_persona_id)
    return _system_persona(db)


@app.get("/conversations/{thread_id}/persona", response_model=PersonaOut)
def get_conversation_persona(
    thread_id: str,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    internal_thread_id = _config(current, thread_id)["configurable"]["thread_id"]
    row = db.execute(
        select(Conversation).where(Conversation.thread_id == internal_thread_id)
    ).scalar_one_or_none()
    if row is None:
        persona = (
            _visible_persona(db, current, current.default_persona_id)
            if current.default_persona_id is not None
            else _system_persona(db)
        )
        return persona
    if row.persona_snapshot:
        snapshot = row.persona_snapshot
        persona_id = None
        if row.persona_id is not None:
            persona_id = db.execute(
                select(Persona.id).where(
                    Persona.id == row.persona_id,
                    (Persona.is_system.is_(True)) | (Persona.owner_id == current.id),
                )
            ).scalar_one_or_none()
        return PersonaOut(
            id=persona_id,
            owner_id=snapshot.get("owner_id"),
            name=snapshot.get("name", "已删除角色"),
            role_definition=snapshot.get("role_definition", ""),
            tone=snapshot.get("tone", ""),
            style_rules=snapshot.get("style_rules", ""),
            constraints=snapshot.get("constraints", ""),
            version=snapshot.get("version", 1),
            is_system=snapshot.get("is_system", False),
        )
    if row.persona_id is not None:
        persona = _visible_persona(db, current, row.persona_id)
    elif current.default_persona_id is not None:
        persona = _visible_persona(db, current, current.default_persona_id)
    else:
        persona = _system_persona(db)
    return persona


@app.patch("/conversations/{thread_id}/persona", response_model=PersonaOut)
def update_conversation_persona(
    thread_id: str,
    payload: ConversationPersonaUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    persona = _visible_persona(db, current, payload.persona_id)
    internal_thread_id = _config(current, thread_id)["configurable"]["thread_id"]
    row = db.execute(
        select(Conversation).where(
            Conversation.thread_id == internal_thread_id,
            Conversation.owner_id == current.id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    row.persona_id = persona.id
    row.persona_version = persona.version
    row.persona_snapshot = _persona_snapshot(persona)
    db.commit()
    return persona


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
        conversation = _fixed_title(db, thread_id, internal_thread_id, current.id, snapshot)
        conversations.append(
            _conversation_summary(
                thread_id, updated_at, snapshot,
                conversation.title if conversation is not None else "新会话",
                conversation,
            )
        )
    return conversations


@app.get("/conversations/search", response_model=list[ConversationSearchResult])
def search_conversations(
    request: Request,
    q: str = Query(min_length=1, max_length=120),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search conversation titles through a per-user inverted index."""
    terms = title_terms(q)
    if not terms:
        return []
    thread_ids = db.execute(
        select(ConversationSearchTerm.thread_id)
        .where(
            ConversationSearchTerm.owner_id == current.id,
            ConversationSearchTerm.term.in_(terms),
        )
        .group_by(ConversationSearchTerm.thread_id)
        .having(func.count(func.distinct(ConversationSearchTerm.term)) == len(terms))
    ).scalars().all()
    normalized_query = unicodedata.normalize("NFKC", q).casefold()
    rows = db.execute(
        select(Conversation)
        .where(
            Conversation.owner_id == current.id,
            Conversation.thread_id.in_(thread_ids),
        )
        .order_by(Conversation.updated_at.desc())
    ).scalars().all()
    matches = [
        row for row in rows
        if normalized_query in unicodedata.normalize("NFKC", row.title).casefold()
    ]
    results = []
    for row in matches[:50]:
        thread_id = row.thread_id.removeprefix(f"user-{current.id}:")
        snapshot = request.app.state.agent.get_state(_config(current, thread_id))
        summary = _conversation_summary(thread_id, row.updated_at, snapshot, row.title, row)
        results.append(
            ConversationSearchResult(
                **summary.model_dump(),
            )
        )
    return results


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
    conversation = _fixed_title(db, thread_id, internal_thread_id, current.id, snapshot)
    title = conversation.title if conversation is not None else "新会话"
    summary = _conversation_summary(thread_id, updated_at, snapshot, title, conversation)
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
    sync_title_terms(db, conversation)
    db.commit()
    return ConversationTitle(thread_id=thread_id, title=title)


@app.patch("/conversations/{thread_id}/metadata")
def update_conversation_metadata(
    thread_id: str,
    payload: ConversationMetadataUpdate,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_unset=True)
    if not changes or all(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="请至少提供一个会话属性")
    if payload.tags is not None:
        tags = [tag.strip() for tag in payload.tags]
        if any(not tag or len(tag) > 24 for tag in tags):
            raise HTTPException(status_code=422, detail="标签长度需为 1 到 24 个字符")
        changes["tags"] = list(dict.fromkeys(tags))

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
                "SELECT 1 FROM checkpoints WHERE thread_id = :thread_id "
                "AND checkpoint_ns = '' LIMIT 1"
            ),
            {"thread_id": internal_thread_id},
        ).scalar_one_or_none()
        if checkpoint_exists is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        snapshot = request.app.state.agent.get_state(_config(current, thread_id))
        conversation = _fixed_title(
            db, thread_id, internal_thread_id, current.id, snapshot
        )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    for field, value in changes.items():
        setattr(conversation, field, value)
    db.commit()
    return {
        "thread_id": thread_id,
        "is_favorite": conversation.is_favorite,
        "tags": conversation.tags,
    }


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
async def chat(
    req: ChatRequest,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = {"messages": [_timed_user_message(req.message)]}
    config = _config(current, req.thread_id, run_name="ai-bot-chat", tags=["chat"])
    connection = await asyncio.to_thread(load_connection, current.id)
    context = await asyncio.to_thread(
        _context_for_thread, db, current, req.thread_id, req.persona_id
    )
    lock = await request.app.state.chat_streams.acquire_conversation(
        current.id, req.thread_id
    )
    try:
        async with agent_for_connection(request.app, connection) as agent:
            start_time = time.perf_counter()
            result = await agent.ainvoke(payload, config, context=context)
            await asyncio.to_thread(mark_used, current.id, connection)
            state = await agent.aget_state(config)
            await asyncio.to_thread(
                _bind_persona_after_chat, db, current, req.thread_id, state, req.persona_id,
            )

            pending = _interrupt_payload(result)
            if pending:
                return JSONResponse(pending, status_code=202)
            elapsed = round(time.perf_counter() - start_time, 2)
            await _store_assistant_timing(agent, config, elapsed)
            return {"reply": result["messages"][-1].content, "elapsed": elapsed}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, model_error_message(exc)) from None
    finally:
        lock.release()


@app.post("/chat/resume")
async def chat_resume(
    req: ResumeRequest,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = _config(
        current,
        req.thread_id,
        run_name="ai-bot-chat-resume",
        tags=["chat", "human-in-the-loop"],
    )
    connection = await asyncio.to_thread(load_connection, current.id)
    context = await asyncio.to_thread(_context_for_thread, db, current, req.thread_id)
    lock = await request.app.state.chat_streams.acquire_conversation(
        current.id, req.thread_id
    )
    try:
        async with agent_for_connection(request.app, connection) as agent:
            start_time = time.perf_counter()
            result = await agent.ainvoke(
                Command(resume={"decisions": req.decisions}), config, context=context,
            )
            await asyncio.to_thread(mark_used, current.id, connection)
            state = await agent.aget_state(config)
            await asyncio.to_thread(_bind_persona_after_chat, db, current, req.thread_id, state)

            pending = _interrupt_payload(result)
            if pending:
                return JSONResponse(pending, status_code=202)
            elapsed = round(time.perf_counter() - start_time, 2)
            await _store_assistant_timing(agent, config, elapsed)
            return {"reply": result["messages"][-1].content, "elapsed": elapsed}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, model_error_message(exc)) from None
    finally:
        lock.release()


@app.post("/chat/stream")
def chat_stream(
    req: ChatRequest,
    request: Request,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 在请求开始时读一次快照。设置中途改变，也不会更换正在生成的模型。
    connection = load_connection(current.id)
    config = _config(
        current,
        req.thread_id,
        run_name="ai-bot-chat-regenerate" if req.regenerate else "ai-bot-chat-stream",
        tags=["chat", "stream", *(["regenerate"] if req.regenerate else [])],
    )
    context = _context_for_thread(db, current, req.thread_id, req.persona_id)
    turn_id = req.turn_id or uuid.uuid4().hex
    run = ChatRun(user_id=current.id, thread_id=req.thread_id, turn_id=turn_id)
    registry = request.app.state.chat_streams
    try:
        registry.register(run)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def produce(agent):
        started_at = time.perf_counter()
        try:
            message = req.message
            if req.regenerate:
                message = await _prepare_regeneration(agent, config)
            payload = {"messages": [_timed_user_message(message)]}
            # 生产协程只负责跑模型并把片段放入有界队列；暂停/发送由下面的 SSE 协程处理。
            async for chunk, meta in agent.astream(
                payload, config, context=context, stream_mode="messages"
            ):
                # 只转发主模型节点的文本；中间件内部模型输出和工具原始结果不进入对话。
                if isinstance(meta, dict) and meta.get("langgraph_node") != MAIN_MODEL_NODE:
                    continue
                if isinstance(chunk, ToolMessage) or not chunk.content:
                    continue
                await run.queue.put({"delta": chunk.content})#只往队列里放大模型异步流返回的被过滤后的有效信息

            await asyncio.to_thread(mark_used, current.id, connection)
            state = await agent.aget_state(config)  #读取图状态
            await asyncio.to_thread(
                #同步函数放到工作线程里运行，这样它做数据库 I/O 时，不会卡住当前的异步事件循环。
                #代码读取当前 Agent 状态，更新会话角色等业务信息，
                _bind_persona_after_chat,
                db,
                current,
                req.thread_id,
                state,
                req.persona_id,
            )
            interrupted = False
            #并检查是否有等待用户审批的操作
            for task in state.tasks:
                if task.interrupts:
                    value = task.interrupts[0].value
                    pending = {
                        "status": "awaiting_approval",
                        "action_requests": value["action_requests"],
                        "review_configs": value["review_configs"],
                    }
                    await run.queue.put(pending)
                    interrupted = True
                    break

            elapsed = round(time.perf_counter() - started_at, 2)
            if not interrupted:
                await _store_assistant_timing(agent, config, elapsed)#改时间
            await run.queue.put({"type": "done", "elapsed": elapsed})
            await run.queue.put(None)
        except asyncio.CancelledError:
            raise
        except HTTPException as exc:
            await run.queue.put({"type": "error", "detail": exc.detail})
            await run.queue.put(None)
        except Exception as exc:
            await run.queue.put({"type": "error", "detail": model_error_message(exc)})
            await run.queue.put(None)

    async def run_producer():
        # 这一层只负责个人模型客户端的生命周期；取消时也会关闭 HTTP 连接。
        try:
            async with agent_for_connection(request.app, connection) as agent:
                await produce(agent)
        except Exception as exc:
            await run.queue.put({"type": "error", "detail": model_error_message(exc)})
            await run.queue.put(None)
#把数据包装成 SSE（服务器发送事件）格式
    def encode_event(payload, sequence: int) -> str:
        #payload 是 "[DONE]"，它就原样放进 data:，而不把它当普通 JSON 编码。
        data = "[DONE]" if payload == "[DONE]" else json.dumps(payload, ensure_ascii=False)
        # SSE id 便于前端识别发送顺序；服务端目前不保存历史事件供断线重放。
        return f"id: {sequence}\ndata: {data}\n\n"

    #SSE协程
    async def event_gen():
        lock = None
        try:
            lock = await registry.activate(run)
            if not run.cancelled:
                run.producer = asyncio.create_task(run_producer())
            sequence = 0
            replay_remaining = 0 #暂停之后，本次恢复时，已经积压了多少个片段”。
            sequence += 1
            run.last_sent_seq = sequence
            yield encode_event({"type": "started", "turn_id": turn_id}, sequence)#第一条事件是 started，带上 turn_id，告诉前端这轮对话开始了。
# 这段是SSE的发送循环，在附近。它不断从队列取模型片段，检查暂停或取消状态，再决定发给浏览器还是结束连接。
            while True:
                try:#asyncio.wait_for(某个异步操作, timeout=15) 的意思是：最多等这个操作 15 秒；完成了就拿结果，超时了就抛出 TimeoutError。
                    item = await asyncio.wait_for(run.queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"#如果15秒没反应抛异常后发个keeplive续长连接
                    continue

                if item is CANCELLED_EVENT or run.cancelled:
                    sequence += 1
                    run.last_sent_seq = sequence
                    yield encode_event(CANCELLED_EVENT, sequence)
                    break
                was_paused = not run.resumed.is_set()
#run.resumed 是一个“允许发送”的开关。暂停时它被 clear()，循环就在 await run.resumed.wait() 这里
                # 暂停时保留当前片段和队列内容；继续后从这个片段接着发，不重跑模型。
                while not run.resumed.is_set() and not run.cancelled:#还没收到“继续”信号，并且任务还没取消时，就继续等待。
                    try:
                        await asyncio.wait_for(run.resumed.wait(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                if run.cancelled:
                    sequence += 1
                    run.last_sent_seq = sequence
                    yield encode_event(CANCELLED_EVENT, sequence)
                    break
                if was_paused:
                    replay_remaining=run.queue.qsize() + 1
                if item is None:
                    sequence += 1
                    run.last_sent_seq = sequence
                    yield encode_event("[DONE]", sequence)
                    break

                sequence += 1
                run.last_sent_seq = sequence
                yield encode_event(item, sequence)
                #await asyncio.sleep(STREAM_REPLAY_INTERVAL)
                # 暂停期间生产端仍在往队列里灌片段；恢复后若一口气 yield 完，浏览器
                # 会在同一帧把积压内容全部渲染出来。这里只在队列还有积压时留出间隔，
                # 让片段按节奏吐出，队列排空后自动恢复全速，正常流式不受影响。
                if isinstance(item, dict) and "delta" in item and replay_remaining > 0:
                    replay_remaining -= 1
                    if replay_remaining > 0:
                        await asyncio.sleep(STREAM_REPLAY_INTERVAL)
        finally:
            # 浏览器断开连接也会走这里：清理模型任务、移除 turn_id 并释放会话锁。
            if run.producer is not None and not run.producer.done():
                registry.cancel(run)
                run.producer.cancel()
            if run.producer is not None:
                await asyncio.gather(run.producer, return_exceptions=True)
            #设置完成状态
            registry.finish(run, lock)

    # 不是递归，而是把一个异步生成器交给 StreamingResponse，让它逐段读取并发送
    return StreamingResponse(
        event_gen(),#调用它，得到它这个异步生成器对象，它执行到yield交出一段，响应再发给浏览器再读下一段直到结束
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/turns/{turn_id}/pause")
async def pause_chat_turn(
    turn_id: str,
    request: Request,
    current: User = Depends(get_current_user),
):
    run = request.app.state.chat_streams.get(current.id, turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="生成任务不存在或已结束")
    return request.app.state.chat_streams.pause(run)


@app.post("/chat/turns/{turn_id}/resume")
async def resume_chat_turn(
    turn_id: str,
    request: Request,
    current: User = Depends(get_current_user),
):
    run = request.app.state.chat_streams.get(current.id, turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="生成任务不存在或已结束")
    return request.app.state.chat_streams.resume(run)


@app.post("/chat/turns/{turn_id}/cancel")
async def cancel_chat_turn(
    turn_id: str,
    request: Request,
    current: User = Depends(get_current_user),
):
    run = request.app.state.chat_streams.get(current.id, turn_id)
    if run is None:
        raise HTTPException(status_code=404, detail="生成任务不存在或已结束")
    return request.app.state.chat_streams.cancel(run)
