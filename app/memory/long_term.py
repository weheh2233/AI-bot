from contextlib import contextmanager
from langgraph.store.postgres import PostgresStore
from psycopg_pool import ConnectionPool
from app.config import settings
from app.embeddings import EMBED_DIMS, get_embeddings


@contextmanager
def store_context():
    database_url = settings.database_url
    if not database_url:
        raise RuntimeError("没有配置 DATABASE_URL")

    with ConnectionPool(
        conninfo=database_url,
        max_size=10,
        open=True,
        kwargs={"autocommit": True},
    ) as pool:
        store = PostgresStore(
            pool,
            index={
                "dims": EMBED_DIMS,
                "embed": get_embeddings(),
                # key+value 一起向量化：key 名（如"居住地"）提供语义锚点，
                # 否则短 value（如"广州"）向量太稀薄，检索不到。
                "fields": ["key", "value"],
            },
        )
        store.setup()      # 建表 + 建向量索引，只跑一次（幂等）
        yield store
