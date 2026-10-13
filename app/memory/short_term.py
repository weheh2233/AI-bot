import os
from contextlib import contextmanager

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

load_dotenv()


@contextmanager
def checkpointer_context():
    """短期记忆：对话历史，底层用连接池持有连接。"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("没有配置 DATABASE_URL")

    with ConnectionPool(
        conninfo=database_url,
        max_size=10,
        open=True,
        kwargs={"autocommit": True},
    ) as pool:
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        yield checkpointer
