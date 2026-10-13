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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )



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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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
