"""初始化业务数据库（创建 users 表等）。

用法： python -m app.db_init
幂等： 表已存在时不会重复创建，也不会清空数据。
"""
from sqlalchemy import inspect, text
from app.database import Base, engine
from app import models  # noqa: F401  导入以把模型注册到 Base.metadata


def _migrate_users_add_is_admin() -> None:
    """给已存在的 users 表补 is_admin 列（幂等）。

    create_all 只建新表、不改已存在的表。老库的 users 没有 is_admin，
    这里做一次幂等 ALTER 补上，避免 DROP 重建丢数据。
    """
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    if "is_admin" in {c["name"] for c in inspector.get_columns("users")}:
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT false")
        )


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    _migrate_users_add_is_admin()
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成（表已就绪）。")
