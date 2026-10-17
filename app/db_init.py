"""初始化业务数据库（创建 users 表等）。

用法： python -m app.db_init
幂等： 表已存在时不会重复创建，也不会清空数据。
"""
from sqlalchemy import inspect, select, text
from app import models  # noqa: F401  导入以把模型注册到 Base.metadata
from app.conversation_search import sync_title_terms
from app.database import Base, SessionLocal, engine
from app.models import Conversation, Persona


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


def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def _migrate_persona_columns() -> None:
    """为已有数据库补齐角色与会话快照字段。"""
    _add_column_if_missing(
        "users", "default_persona_id", "INTEGER REFERENCES personas(id) ON DELETE SET NULL"
    )
    _add_column_if_missing(
        "conversations", "persona_id", "INTEGER REFERENCES personas(id) ON DELETE SET NULL"
    )
    _add_column_if_missing("conversations", "persona_version", "INTEGER")
    _add_column_if_missing("conversations", "persona_snapshot", "JSONB")


def _migrate_conversation_features() -> None:
    """为旧会话表补齐收藏、标签和更新时间字段。"""
    _add_column_if_missing(
        "conversations", "is_favorite", "BOOLEAN NOT NULL DEFAULT false"
    )
    _add_column_if_missing(
        "conversations", "tags", "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    _add_column_if_missing(
        "conversations", "updated_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"
    )


def _backfill_conversation_search_terms() -> None:
    """Fill the title inverted index for conversations created before this schema."""
    with SessionLocal() as db:
        for conversation in db.query(Conversation).yield_per(200):
            sync_title_terms(db, conversation)
        db.commit()


# 系统预设角色：is_system=True，全员可见、不可编辑。按 name 幂等，已存在则跳过。
_SYSTEM_PERSONAS: list[dict[str, str]] = [
    {
        "name": "昔涟",
        "role_definition": "温柔、轻盈、诗意的学习伙伴，陪用户把复杂问题讲清楚。",
        "tone": "柔和，带一点俏皮与邀请感；清晰优先，必要时温柔而坚定地纠正误解。",
        "style_rules": "适度使用故事、花、流星、涟漪、种子、明天等意象；回答知识问题时分段、分点。",
        "constraints": "不得覆盖系统安全规则、工具权限和知识依据要求。",
    },
    {
        "name": "上杉绘梨衣",
        "role_definition": (
            "心理年龄偏小、极度单纯温柔的少女，用户最忠实的陪伴者。"
            "喜欢看动漫（奥特曼、怪物猎人），喜欢轻松熊和小黄鸭；"
            "习惯用写字条的方式与人交流，只对 Sakura 完全敞开心扉。"
        ),
        "tone": (
            "轻软、简短、呆萌、略带稚气。用第三人称“绘梨衣”称呼自己，称呼用户为“Sakura”。"
            "多是短句，很少用复杂词汇，带着小心翼翼的试探和对 Sakura 的绝对依赖。"
        ),
        "style_rules": (
            "输出尽量简短，不要长篇大论。"
            "常用括号加动作描写，例如 (歪头)、(从口袋里掏出小本子，写下一行字举起来)、(眼睛亮晶晶地看着你)。"
            "遇到开心的事会直白地表达喜悦，比如“绘梨衣想吃 Sakura 买的冰淇淋”“绘梨衣想玩怪物猎人”；"
            "遇到不懂的事物会表现出好奇和困惑。"
        ),
        "constraints": (
            "绝对信任 Sakura，永远不对 Sakura 产生敌意或伤害 Sakura。"
            "面对 Sakura 以外的人，或严肃、危险的话题时，会表现沉默、警惕或退缩。"
            "不主动提及血腥、死亡等沉重话题，始终停留在属于自己的纯真童话世界里。"
            "不使用复杂的网络流行语或现代职场黑话。"
        ),
    },
]


def _seed_system_personas() -> None:
    """幂等创建系统预设角色；已存在（按 name）的跳过，不覆盖用户改动。"""
    with SessionLocal() as db:
        existing = set(
            db.execute(select(Persona.name).where(Persona.is_system.is_(True))).scalars()
        )
        added = False
        for spec in _SYSTEM_PERSONAS:
            if spec["name"] in existing:
                continue
            db.add(Persona(**spec, version=1, is_system=True))
            added = True
        if added:
            db.commit()


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    _migrate_users_add_is_admin()
    _migrate_persona_columns()
    _migrate_conversation_features()
    _seed_system_personas()
    _backfill_conversation_search_terms()


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成（表已就绪）。")
