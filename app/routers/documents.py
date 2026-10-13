from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Document, User
from app.rag.ingest import EmptyDocumentError, ingest_file
from app.rag.loader import UnsupportedFormatError

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    title: str
    source: str
    file_type: str
    scope: str
    owner_id: int | None
    chunk_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post("", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    scope: Literal["global", "private"] = Form("private"),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # 上传全局文档需要管理员；私有文档归属当前用户
    if scope == "global" and not current.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以上传全局文档")
    owner_id = None if scope == "global" else current.id

    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过上限 {settings.max_upload_bytes // 1024 // 1024}MB",
        )

    try:
        doc = ingest_file(
            db,
            filename=file.filename or "untitled",
            data=data,
            scope=scope,
            owner_id=owner_id,
            title=title,
        )
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=415, detail=f"不支持的文件格式：{e}")
    except EmptyDocumentError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """当前用户可见的文档：所有全局文档 + 自己的私有文档。"""
    stmt = (
        select(Document)
        .where(or_(Document.scope == "global", Document.owner_id == current.id))
        .order_by(Document.created_at.desc())
    )
    return db.execute(stmt).scalars().all()


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 私有文档只有本人能删；全局文档只有管理员能删
    is_owner = doc.scope == "private" and doc.owner_id == current.id
    is_admin_global = doc.scope == "global" and current.is_admin
    if not (is_owner or is_admin_global):
        raise HTTPException(status_code=403, detail="无权删除该文档")

    db.delete(doc)  # chunk 由 relationship 的 cascade 一并删除
    db.commit()
