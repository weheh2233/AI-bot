import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.api import app
from app.database import SessionLocal
from app.db_init import init_db
from app.models import Document, DocumentChunk, User

TIMEOUT = 120

# 本次测试会话注册的所有用户，会话结束时统一清理
_created_user_ids: list[int] = []
# 测试期间创建的文档 id（global 文档 owner 为空，不随用户级联删，需单独记录）
_created_document_ids: list[int] = []


@pytest.fixture(scope="session", autouse=True)
def _ensure_db():
    init_db()


@pytest.fixture(scope="session")
def client():
    # with 触发 lifespan：建连接池 + 构建 agent
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _cleanup_after_session(client):
    """测试结束后清掉本次注册的用户、其长期记忆、以及按用户前缀命名的会话。

    测试跑真实 DB，不清理会不断累积（用户 / 记忆 / checkpoint）。
    """
    yield
    if not _created_user_ids and not _created_document_ids:
        return

    # 0) 测试创建的文档（global 文档 owner 为空，不随用户级联删；chunk 靠 FK 级联删）
    if _created_document_ids:
        with SessionLocal() as db:
            for did in _created_document_ids:
                db.query(DocumentChunk).filter_by(document_id=did).delete()
                db.query(Document).filter_by(id=did).delete()
            db.commit()

    # 1) 长期记忆（store 的 users/<id>/ 命名空间）
    from app.memory.long_term import store_context

    if _created_user_ids:
        with store_context() as store:
            for uid in _created_user_ids:
                ns = ("users", str(uid), "memories")
                for item in store.search(ns, limit=1000):
                    store.delete(ns, item.key)

    # 2) 会话 checkpoint（api 里实际存储键为 "user-{id}:..."）
    with SessionLocal() as db:
        for uid in _created_user_ids:
            pattern = f"user-{uid}:%"
            db.execute(
                text("DELETE FROM checkpoints WHERE thread_id LIKE :p"), {"p": pattern}
            )
            db.execute(
                text("DELETE FROM checkpoint_blobs WHERE thread_id LIKE :p"),
                {"p": pattern},
            )
            db.execute(
                text("DELETE FROM checkpoint_writes WHERE thread_id LIKE :p"),
                {"p": pattern},
            )
        # 3) 用户记录
        db.execute(delete(User).where(User.id.in_(_created_user_ids)))
        db.commit()


@pytest.fixture
def register(client):
    """返回一个注册工厂：调用 register() 每次生成一个全新用户，返回 (user_id, token)。

    做成工厂（而非直接返回一个用户）是因为 pytest fixture 同名在一次测试里只实例化
    一次——需要多个用户的测试（如隔离测试）必须能多次调用它。
    """

    def _register():
        username = f"test-{uuid.uuid4().hex[:8]}"
        r = client.post(
            "/auth/register",
            json={"username": username, "password": "secret123"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        _created_user_ids.append(data["user_id"])
        # 密码固定为 "secret123"，供需要复测登录的用例使用
        return data["user_id"], data["access_token"], username

    return _register


@pytest.fixture
def track_document():
    """登记一个文档 id，供会话结束清理（global 文档不随用户级联删）。"""

    def _track(doc_id: int):
        _created_document_ids.append(doc_id)

    return _track


@pytest.fixture
def upload(client, track_document):
    """返回上传文档的工厂：upload(token, filename, content, scope="private", title=None)。

    上传成功即登记文档 id，会话结束时统一清理。
    """

    def _upload(token, filename, content, scope="private", title=None):
        headers = {"Authorization": f"Bearer {token}"}
        data = {"scope": scope}
        if title is not None:
            data["title"] = title
        r = client.post(
            "/documents",
            files={"file": (filename, content, "application/octet-stream")},
            data=data,
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            track_document(r.json()["id"])
        return r

    return _upload


@pytest.fixture
def chat(client):
    """返回一个带鉴权调 /chat 的函数 chat(token, message, thread_id) -> reply。

    写记忆会被 HumanInTheLoopMiddleware 拦下挂起审批（/chat 返回 202），
    这里自动 approve 并 resume 直到拿到最终回复——既断言最终结果，又覆盖审批链路。
    """

    def _chat(token, message, thread_id):
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post(
            "/chat",
            json={"message": message, "thread_id": thread_id},
            headers=headers,
            timeout=TIMEOUT,
        )
        # 一轮可能有多次中断（模型再次触发写记忆），循环审批至结束
        for _ in range(5):
            if resp.status_code == 200:
                return resp.json()["reply"]
            assert resp.status_code == 202, resp.text
            decisions = [
                {"type": "approve"} for _ in resp.json()["action_requests"]
            ]
            resp = client.post(
                "/chat/resume",
                json={"thread_id": thread_id, "decisions": decisions},
                headers=headers,
                timeout=TIMEOUT,
            )
        raise AssertionError(f"审批中断超过 5 轮仍未结束：{resp.text}")

    return _chat
