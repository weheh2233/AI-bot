"""共享的 embedding 客户端。

记忆检索与文档 RAG 用同一套 Qwen embedding，维度也必须一致，
所以客户端和 EMBED_DIMS 都集中在这里，各模块统一从这里取。
"""

from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import settings

# Qwen qwen3.7-text-embedding-flash 的输出维度
EMBED_DIMS = 1024
# DashScope 单次 embedding 请求最多 20 条，超过报 InvalidParameter
EMBED_BATCH_SIZE = 20


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    """进程级单例。底层 httpx client 会被复用，避免每次检索重建连接。"""
    return OpenAIEmbeddings(
        model="qwen3.7-text-embedding-flash",
        api_key=settings.embedding_model_api_key,
        base_url=settings.embedding_model_base_url,
        dimensions=EMBED_DIMS,
        check_embedding_ctx_length=False,
    )
