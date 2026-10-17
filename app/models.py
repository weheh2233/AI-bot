from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.embeddings import EMBED_DIMS


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # 管理员是 DB 层字段，不靠用户名白名单（开放注册下白名单可被抢注）。
    # server_default 保证裸 SQL 插入也有默认值，不只靠 ORM。
    is_admin: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )
    default_persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )



class UserModelConfig(Base):
    """每个用户最多一组模型连接；不配置就使用服务器默认。Key 只存密文。"""

    __tablename__ = "user_model_configs"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    base_url: Mapped[str] = mapped_column(String(512))
    model_name: Mapped[str] = mapped_column(String(200))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    # 旧请求结束时只更新自己使用的版本，不能污染刚换的新 Key 的使用时间。
    revision: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base):
    """会话元数据。title 在会话首次出现时固定，不随历史压缩漂移。

    历史压缩（SummarizationMiddleware）会把最早的用户消息移出 state，
    若按 state 现算标题，标题会漂移；因此标题单独落库、只写一次。
    thread_id 存的是带用户前缀的内部 id（见 api._config）。
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    persona_id: Mapped[int | None] = mapped_column(
        ForeignKey("personas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    persona_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 会话使用的角色快照。角色表后续修改或删除都不影响已有会话。
    persona_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), nullable=False
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationSearchTerm(Base):
    """每个标题分词一行，支持按用户隔离的倒排检索。"""

    __tablename__ = "conversation_search_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.thread_id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    term: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("thread_id", "term", name="uq_conversation_search_term"),
        Index("ix_conversation_search_owner_term", "owner_id", "term"),
    )


class Persona(Base):
    """Agent 角色定义。系统预设不可修改，用户角色仅本人可见。"""

    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    role_definition: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(Text)
    style_rules: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    is_system: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Document(Base):
    """一份上传文档的元数据。scope 决定可见范围：global 全员共享，private 仅 owner。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(512))            # 原始文件名
    file_type: Mapped[str] = mapped_column(String(16))          # pdf/txt/md/docx/pptx
    scope: Mapped[str] = mapped_column(String(16), index=True)  # 'global' | 'private'
    # private 文档归属者；global 为 None。删用户时级联删其文档。
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("scope IN ('global', 'private')", name="ck_documents_scope"),
        # 约束 scope 与 owner 的对应关系：global 无主，private 必有主
        CheckConstraint(
            "(scope = 'global' AND owner_id IS NULL) OR "
            "(scope = 'private' AND owner_id IS NOT NULL)",
            name="ck_documents_scope_owner",
        ),
    )


class DocumentChunk(Base):
    """文档切分后的片段 + 向量。scope/owner_id 反范式到这里，权限过滤免 join。"""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIMS))
    # 从 Document 冗余下来：'global' | 'private'；private 时 owner_id 即用户 id
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 不同格式的原文定位信息：PDF 页码、PPT 幻灯片号、DOCX 标题/段落、行号等
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        # 一份文档内 chunk_index 唯一，防重复入库
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        CheckConstraint("scope IN ('global', 'private')", name="ck_chunks_scope"),
        CheckConstraint(
            "(scope = 'global' AND owner_id IS NULL) OR "
            "(scope = 'private' AND owner_id IS NOT NULL)",
            name="ck_chunks_scope_owner",
        ),
        # HNSW：空表即可建、无需训练，适合课设规模。余弦距离索引。
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_scope_owner", "scope", "owner_id"),
    )
