import os
from contextlib import asynccontextmanager, contextmanager

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool, ConnectionPool

load_dotenv()


@contextmanager
def checkpointer_context():
    """同步 checkpoint 池：供历史查询、删除会话和旧同步调用使用。"""
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


@asynccontextmanager
async def async_checkpointer_context():
    """异步 checkpoint 池：供 ainvoke/astream 在等待数据库时不阻塞事件循环。"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("没有配置 DATABASE_URL")

    async with AsyncConnectionPool(
        conninfo=database_url,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    ) as pool:
        # 这是 LangGraph checkpoint 的连接池；业务表的 SQLAlchemy Session 仍然是同步的。
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        yield checkpointer
