"""RAG 检索的端到端测试（走真实 DB + 真实 embedding）。

检索层不依赖 LLM，所以主体测试直接调 search_knowledge，断言稳定；
最后一个用真实 agent 做冒烟，验证能自动检索并引用文档内容。
"""

import uuid


def _body(marker: str) -> bytes:
    """造一段含唯一标记的长文本，长到会被切成多个 chunk。"""
    return (f"资料正文：本文件记录的关键事实是「{marker}」。其余为填充内容。" * 40).encode()


def test_retrieval_hits_private_document(register, upload):
    """用户能检索到自己上传的私有文档。"""
    from app.database import SessionLocal
    from app.rag.retrieval import search_knowledge

    uid, token, _ = register()
    marker = f"彗星{uuid.uuid4().hex[:6]}"
    r = upload(token, "note.txt", _body(marker), scope="private")
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        hits = search_knowledge(db, query="这个文件记录的关键事实是什么", user_id=uid)
    assert hits, "私有文档应能检索到"
    assert any(marker in h["content"] for h in hits)


def test_private_document_isolated_between_users(register, upload):
    """A 的私有文档，B 检索不到。"""
    from app.database import SessionLocal
    from app.rag.retrieval import search_knowledge

    uid_a, token_a, _ = register()
    uid_b, _token_b, _ = register()
    marker = f"机密{uuid.uuid4().hex[:6]}"
    upload(token_a, "secret.txt", _body(marker), scope="private")

    with SessionLocal() as db:
        hits_b = search_knowledge(db, query="这个文件记录的关键事实是什么", user_id=uid_b)
    assert all(marker not in h["content"] for h in hits_b), "B 不该看到 A 的私有文档"


def test_global_document_visible_to_all(register, upload, track_document, client):
    """全局文档，任意用户都能检索到。"""
    from app.database import SessionLocal
    from app.rag.retrieval import search_knowledge

    uid_admin, token_admin, _ = register()
    # 设成管理员才能上传全局文档
    from sqlalchemy import text

    with SessionLocal() as db:
        db.execute(text("UPDATE users SET is_admin=true WHERE id=:i"), {"i": uid_admin})
        db.commit()

    marker = f"教材{uuid.uuid4().hex[:6]}"
    r = upload(token_admin, "book.txt", _body(marker), scope="global")
    assert r.status_code == 200, r.text

    # 另一个普通用户检索
    uid_other, _, _ = register()
    with SessionLocal() as db:
        hits = search_knowledge(db, query="这个文件记录的关键事实是什么", user_id=uid_other)
    assert any(marker in h["content"] for h in hits), "全局文档应对所有用户可见"


def test_pdf_chunk_carries_page_number(register, upload):
    """PDF 的 chunk 带页码定位（loader 按页分段）。"""
    from app.database import SessionLocal
    from app.models import DocumentChunk

    import pymupdf as fitz

    _uid, token, _ = register()
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"第{i + 1}页内容。" * 40)
    r = upload(token, "book.pdf", doc.tobytes(), scope="private")
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]

    with SessionLocal() as db:
        metas = [
            c.meta
            for c in db.query(DocumentChunk).filter_by(document_id=doc_id).all()
        ]
    pages = {m["page_number"] for m in metas if m}
    assert pages, "PDF chunk 应带页码"
    assert all(p in {1, 2, 3} for p in pages)


def test_unsupported_format_rejected(register, upload):
    """不支持的格式返回 415。"""
    _uid, token, _ = register()
    r = upload(token, "data.xlsx", b"anything", scope="private")
    assert r.status_code == 415


def test_empty_document_rejected(register, upload):
    """无有效文本的文档返回 422。"""
    _uid, token, _ = register()
    r = upload(token, "empty.txt", b"   \n  ", scope="private")
    assert r.status_code == 422


def test_non_admin_cannot_upload_global(register, upload):
    """非管理员上传全局文档返回 403。"""
    _uid, token, _ = register()
    r = upload(token, "x.txt", _body("测试"), scope="global")
    assert r.status_code == 403


def test_agent_retrieves_and_answers(register, upload, chat):
    """端到端：agent 自动检索知识库并据其作答（走真实 LLM，冒烟）。"""
    _uid, token, _ = register()
    marker = f"紫罗兰{uuid.uuid4().hex[:6]}"
    r = upload(token, "plan.txt", _body(marker), scope="private")
    assert r.status_code == 200, r.text

    reply = chat(token, "根据我上传的文档，里面记录的关键事实是什么？", f"t-{uuid.uuid4().hex[:8]}")
    assert marker in reply, f"回答未引用文档内容：{reply}"
