"""把上传文件的字节流变成一个 Document + N 个 DocumentChunk。

上游是 loader（分段）和 splitter（段内切分），这里负责批量 embedding 和入库。
scope/owner_id 由调用方（router）依据当前用户权限算好后传入，本模块不判权限。
"""

from sqlalchemy.orm import Session

from app.embeddings import EMBED_BATCH_SIZE, get_embeddings
from app.models import Document, DocumentChunk
from app.rag.loader import extract_segments
from app.rag.splitter import  route_file_type


class EmptyDocumentError(Exception):
    """文档解析后没有可入库文本（如无文字层的扫描件 PDF）。调用方据此返回 4xx。"""


def ingest_file(
    db: Session,
    *,
    filename: str,
    data: bytes,
    scope: str,
    owner_id: int | None,
    title: str | None = None,
) -> Document:
    """解析 → 段内切分 → 批量 embedding → 建 Document + chunks，单事务提交。"""
    segments = extract_segments(filename, data)
    chunks = route_file_type(segments)
    if not chunks:
        raise EmptyDocumentError(f"「{filename}」没有解析出可用文本")

    # 批量 embedding。chunk_size 限制单次请求条数（DashScope 上限 20），
    # 超过会自动分批多次请求。
    texts = [content for content, _ in chunks]
    vectors = get_embeddings().embed_documents(texts, chunk_size=EMBED_BATCH_SIZE)

    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    doc = Document(
        title=title or filename,
        source=filename,
        file_type=file_type,
        scope=scope,
        owner_id=owner_id,
        chunk_count=len(chunks),
    )
    # scope/owner_id 反范式到每个 chunk，检索时免 join
    doc.chunks = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):#zip([A1,A2,A3], [B1,B2,B3])   # 产出 (A1,B1), (A2,B2), (A3,B3)
        content, meta = chunk  # chunk 是 (文本, 定位)
        doc.chunks.append(
            DocumentChunk(
                chunk_index=i,
                content=content,
                embedding=vector,
                scope=scope,
                owner_id=owner_id,
                meta=meta,  # PDF 为 {"page_number": n}，其余为 None
            )
        )

    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
