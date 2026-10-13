import json

from langchain.tools import ToolRuntime, tool

from app.database import SessionLocal
from app.rag.retrieval import search_knowledge


@tool
def search_knowledge_base(query: str, runtime: ToolRuntime) -> str:
    """在知识库中检索与问题相关的内容（含全局教材资料与当前用户上传的私有文档）。

    当用户询问教材、课件、上传文档、课程资料相关内容时调用，
    把用户的原始问题作为 query 传入。返回若干相关片段供你引用作答。
    """
    user_id = int(runtime.context.user_id)
    # ToolRuntime 不提供 db 句柄，这里自开一个 session，用完即关
    with SessionLocal() as db:
        hits = search_knowledge(db, query=query, user_id=user_id)

    if not hits:
        return "知识库中没有检索到相关内容。"
    return json.dumps(hits, ensure_ascii=False)
