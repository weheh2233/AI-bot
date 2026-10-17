"""个人模型配置：加密保存、读取请求快照、构建本轮 Agent。

只给聊天/历史摘要替换模型，向量模型和搜索服务仍由服务器统一配置。
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from langchain_openai import ChatOpenAI
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.model_transport import NoSyncModelTransport, PublicModelTransport, validate_base_url
from app.models import UserModelConfig


@dataclass(frozen=True)
class ModelConnection:
    base_url: str
    model_name: str
    api_key: str = field(repr=False)
    revision: str | None = None


def key_cipher() -> Fernet:
    try:
        return Fernet(settings.model_settings_encryption_key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise HTTPException(503, "服务器尚未正确配置个人 Key 加密密钥，请联系管理员") from None


def storage_ready() -> bool:
    try:
        key_cipher()
        return True
    except HTTPException:
        return False


def decrypt_key(row: UserModelConfig) -> str:
    try:
        return key_cipher().decrypt(row.encrypted_api_key.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise HTTPException(503, "个人 Key 无法解密，请重新保存或删除后使用默认模型") from None


def config_status(db: Session, user_id: int) -> dict:
    row = db.get(UserModelConfig, user_id)
    # 刻意不返回 Key，也不返回密文；页面只需要知道是否配置过。
    return {
        "configured": row is not None,
        "storage_ready": storage_ready(),
        "base_url": row.base_url if row else "",
        "model_name": row.model_name if row else "",
        "updated_at": row.updated_at if row else None,
        "last_used_at": row.last_used_at if row else None,
        "default_model_name": settings.deepseek_model,
    }


def resolve_input(db: Session, user_id: int, base_url: str, model_name: str,
                  api_key: str | None) -> ModelConnection:
    try:
        base_url = validate_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    model_name = model_name.strip()
    if not model_name or any(ord(c) < 32 or ord(c) == 127 for c in model_name):
        raise HTTPException(400, "请填写有效的模型名")
    row = db.get(UserModelConfig, user_id)
    if not api_key:
        if row is None:
            raise HTTPException(400, "首次配置必须填写 API Key")
        if row.base_url != base_url:
            raise HTTPException(400, "修改 Base URL 时必须重新填写 Key，避免将旧 Key 发给其他服务")
        api_key = decrypt_key(row)
    if any(ord(c) < 33 or ord(c) > 126 for c in api_key):
        raise HTTPException(400, "API Key 不能包含空白或非 ASCII 字符")
    return ModelConnection(base_url, model_name, api_key)


def save_config(db: Session, user_id: int, connection: ModelConnection) -> dict:
    encrypted = key_cipher().encrypt(connection.api_key.encode()).decode()
    row = db.get(UserModelConfig, user_id)
    if row is None:
        row = UserModelConfig(user_id=user_id)
        db.add(row)
    row.base_url = connection.base_url
    row.model_name = connection.model_name
    row.encrypted_api_key = encrypted
    row.revision = uuid.uuid4().hex
    row.updated_at = datetime.now(timezone.utc)
    row.last_used_at = None
    db.commit()
    return config_status(db, user_id)


def load_connection(user_id: int) -> ModelConnection | None:
    # 自己开一个短 Session，不与长时间运行的 SSE 共用数据库连接。
    with SessionLocal() as db:
        row = db.get(UserModelConfig, user_id)
        if row is None:
            return None
        return ModelConnection(row.base_url, row.model_name, decrypt_key(row), row.revision)


def mark_used(user_id: int, connection: ModelConnection | None):
    """最后使用 = 这组配置最近一次成功完成聊天/审批回复；测试连接不计入。"""
    if connection is None or connection.revision is None:
        return
    with SessionLocal() as db:
        db.execute(update(UserModelConfig).where(
            UserModelConfig.user_id == user_id,
            UserModelConfig.revision == connection.revision,
        ).values(last_used_at=datetime.now(timezone.utc)))
        db.commit()


@asynccontextmanager
async def personal_model(connection: ModelConnection):
    # 禁用代理和重定向，避免 Key 被转送。连接只存在于本轮，用完立即关闭。
    transport = PublicModelTransport(connection.base_url)
    async with httpx.AsyncClient(
        transport=transport, follow_redirects=False, trust_env=False,
        timeout=httpx.Timeout(60, connect=10),
    ) as async_client:
        with httpx.Client(transport=NoSyncModelTransport(), trust_env=False) as sync_client:
            yield ChatOpenAI(
                model=connection.model_name, api_key=connection.api_key,
                base_url=connection.base_url, http_async_client=async_client,
                http_client=sync_client, max_retries=0, timeout=60,
                # 用户填的是服务商的原始模型名，不做 provider 前缀解析。
                use_responses_api=False,
            )


@asynccontextmanager
async def agent_for_connection(app, connection: ModelConnection | None):
    if connection is None:
        yield app.state.async_agent
        return
    from app.agent.bot import get_agent

    async with personal_model(connection) as model:
        yield get_agent(
            app.state.async_agent.checkpointer, app.state.async_agent.store,
            async_mode=True, model=model,
        )


def model_error_message(exc: Exception) -> str:
    # 不把服务商的原始异常返回给浏览器：它可能包含 Authorization、URL 或请求体。
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "模型服务拒绝了凭证，请检查 API Key 和模型权限"
    if status == 429:
        return "模型服务限流或额度不足，请稍后重试或检查余额"
    if status == 404:
        return "模型或接口不存在，请检查 Base URL 和模型名"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "模型连接超时，请检查服务地址或稍后重试"
    return "模型调用失败，请检查 Base URL、API Key、模型名及工具调用兼容性"


async def test_connection(connection: ModelConnection) -> None:
    # 测试只发送固定短句，不携带用户历史、资料或记忆；仍可能产生少量服务商费用。
    try:
        async with asyncio.timeout(20):
            async with personal_model(connection) as model:
                await model.ainvoke("Reply with OK.", max_tokens=16)
    except Exception as exc:
        raise HTTPException(400, model_error_message(exc)) from None
