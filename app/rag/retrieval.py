#向量检索 + scope 过滤

from sqlalchemy import select, or_, and_, cast
from pgvector.sqlalchemy import Vector
from app.embeddings import get_embeddings, EMBED_DIMS
from app.models import Document, DocumentChunk


RAG_TOP_K=5
RAG_MIN_SCORE = 0.4
RAG_MAX_DISTANCE = 1.0 - RAG_MIN_SCORE   # 0.6：相似度 0.4 对应距离 0.6

def search_knowledge(db, *, query: str,
                     user_id: int,
                     top_k=RAG_TOP_K) -> list[dict]:
    vector_query=get_embeddings().embed_query(query)
    vector_query_param = cast(vector_query, Vector(EMBED_DIMS))#embed_query 返回的是 Python list，psycopg 不知道要当 vector 传，转换一下
    dist = DocumentChunk.embedding.cosine_distance(vector_query_param)#算距离
    #组装查询（过滤 + 排序 + 阈值）
    stmt=(
        select(DocumentChunk,Document.title,Document.source,Document.file_type,dist.label("distance"))
        .join (Document,Document.id==DocumentChunk.document_id)
        .where(or_(
            DocumentChunk.scope == "global",
            and_(DocumentChunk.scope == "private", DocumentChunk.owner_id == user_id),
        ))
        .where(dist <= RAG_MAX_DISTANCE)
        .order_by(dist)          # 距离升序 = 最相关在前（cosine distance 越小越像）
        .limit(top_k)
        )

    rows = db.execute(stmt).all()

    return [{
        "document_id": r.DocumentChunk.document_id,
        "title": r.title,
        "source": r.source,
        "file_type": r.file_type,
        "content": r.DocumentChunk.content,
        "locator": r.DocumentChunk.meta or {},  # PDF 有页码，其余空 dict
        "similarity": 1.0 - r.distance,
    } for r in rows]
