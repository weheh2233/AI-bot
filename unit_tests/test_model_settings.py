"""隔离测试：使用临时 SQLite 和替身模型，不调用真实模型、不改开发库。"""

import asyncio
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import api as api_module, model_settings as service
from app.auth import create_token, hash_password, verify_password
from app.database import get_db
from app.model_transport import PublicModelTransport, public_ip, validate_base_url
from app.models import User, UserModelConfig
from app.routers import settings as settings_router


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    User.__table__.create(engine)
    UserModelConfig.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(settings_router, "SessionLocal", factory)
    monkeypatch.setattr(service.settings, "model_settings_encryption_key", Fernet.generate_key().decode())
    with factory() as db:
        db.add_all([User(id=1, username="alice", password_hash=hash_password("old-pass")),
                    User(id=2, username="bob", password_hash=hash_password("bob-pass"))])
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def client(database):
    def db_override():
        with database() as db:
            yield db
    api_module.app.dependency_overrides[get_db] = db_override
    # 不进入 lifespan：只测试接口逻辑，不启动真实 PostgreSQL saver。
    client = TestClient(api_module.app)
    client.headers["Authorization"] = f"Bearer {create_token(1)}"
    yield client
    client.close()
    api_module.app.dependency_overrides.clear()


def config(**changes):
    return {"base_url": "https://models.example.com/v1", "model_name": "custom/model:1",
            "api_key": "test-personal-secret", **changes}


def test_encryption_isolation_update_delete_and_default(client, database):
    assert client.get("/settings/model").json()["configured"] is False
    assert service.load_connection(1) is None
    result = client.put("/settings/model", json=config())
    assert result.status_code == 200
    status = result.json()
    assert status["configured"] and status["updated_at"] and status["last_used_at"] is None
    assert "secret" not in result.text and "api_key" not in result.text
    with database() as db:
        row = db.get(UserModelConfig, 1)
        assert row.encrypted_api_key != config()["api_key"]
        assert service.decrypt_key(row) == config()["api_key"]
    connection = service.load_connection(1)
    assert config()["api_key"] not in repr(connection)
    assert connection.model_name == "custom/model:1"
    service.mark_used(1, connection)
    assert client.get("/settings/model").json()["last_used_at"]
    result = client.put("/settings/model", json=config(api_key=None, model_name="other-model"))
    assert result.status_code == 200
    assert result.json()["last_used_at"] is None
    service.mark_used(1, connection)  # 旧轮次不能更新新配置的使用时间。
    assert client.get("/settings/model").json()["last_used_at"] is None
    client.headers["Authorization"] = f"Bearer {create_token(2)}"
    assert not client.get("/settings/model").json()["configured"]
    client.delete("/settings/model")
    assert service.load_connection(1) is not None
    client.headers["Authorization"] = f"Bearer {create_token(1)}"
    assert not client.delete("/settings/model").json()["configured"]
    assert service.load_connection(1) is None
    service.mark_used(1, connection)  # 删除后，旧请求结束不能重新插入配置。
    assert service.load_connection(1) is None


def test_new_endpoint_requires_new_key_and_never_silently_falls_back(client, monkeypatch):
    assert client.put("/settings/model", json=config(api_key=None)).status_code == 400
    assert client.put("/settings/model", json=config()).status_code == 200
    assert client.put("/settings/model", json=config(
        base_url="https://different.example.com/v1", api_key=None,
    )).status_code == 400
    monkeypatch.setattr(service.settings, "model_settings_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(HTTPException) as exc:
        service.load_connection(1)
    assert exc.value.status_code == 503
    assert client.get("/settings/model").json()["configured"]
    assert client.delete("/settings/model").status_code == 200
    assert service.load_connection(1) is None


def test_no_encryption_secret_disables_personal_storage_only(client, monkeypatch):
    monkeypatch.setattr(service.settings, "model_settings_encryption_key", "")
    status = client.get("/settings/model").json()
    assert not status["storage_ready"]
    assert service.load_connection(1) is None
    assert client.put("/settings/model", json=config()).status_code == 503


@pytest.mark.parametrize("url", [
    "http://example.com/v1", "https://localhost/v1", "https://127.0.0.1/v1",
    "https://10.0.0.1", "https://169.254.169.254", "https://[::1]",
    "https://192.168.0.1", "https://example.com:8443", "https://user:pass@example.com",
    "https://example.com?key=secret", "https://example.com#fragment",
    "https://example.com\\@127.0.0.1", "https://example.com\n", "https://[::ffff:127.0.0.1]",
])
def test_invalid_base_urls(url):
    # 前后空白会 trim，URL 内部的控制字符则拒绝。
    if url.endswith("\n"):
        url = "https://exa\nmple.com"
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_dns_resolution_checks_all_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(ValueError):
        public_ip("models.example.com")


async def test_transport_connects_validated_ip_and_keeps_tls_host(monkeypatch):
    from app import model_transport
    monkeypatch.setattr(model_transport, "public_ip", lambda host: "93.184.216.34")
    seen = []
    async def handler(request):
        seen.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example.com"})
    transport = PublicModelTransport("https://models.example.com/v1")
    await transport.inner.aclose()
    transport.inner = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        response = await client.post("https://models.example.com/v1/chat/completions",
                                     headers={"Authorization": "Bearer secret"}, json={"x": 1})
        assert response.status_code == 307
        assert len(seen) == 1
        assert seen[0].url.host == "93.184.216.34"
        assert seen[0].headers["Host"] == "models.example.com"
        assert seen[0].extensions["sni_hostname"] == "models.example.com"
        with pytest.raises(ValueError):
            await client.post("https://other.example.com/v1")


def test_password_change_checks_old_and_keeps_existing_login(client, database):
    assert client.post("/auth/password", json={
        "old_password": "wrong", "new_password": "new-pass",
    }).status_code == 400
    assert client.post("/auth/password", json={
        "old_password": "old-pass", "new_password": "old-pass",
    }).status_code == 400
    assert client.post("/auth/password", json={
        "old_password": "old-pass", "new_password": "汉" * 25,
    }).status_code == 400
    assert client.post("/auth/password", json={
        "old_password": "old-pass", "new_password": "new-pass",
    }).status_code == 200
    with database() as db:
        assert verify_password("new-pass", db.get(User, 1).password_hash)
        assert not verify_password("old-pass", db.get(User, 1).password_hash)
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/login", json={"username": "alice", "password": "old-pass"}).status_code == 401
    assert client.post("/auth/login", json={"username": "alice", "password": "new-pass"}).status_code == 200


def test_sensitive_validation_does_not_echo_inputs(client):
    response = client.put("/settings/model", json=config(api_key={"secret": "DO-NOT-ECHO"}))
    assert response.status_code == 422
    assert "DO-NOT-ECHO" not in response.text
    response = client.post("/auth/password", json={"old_password": "DO-NOT-ECHO", "new_password": "123"})
    assert response.status_code == 422
    assert "DO-NOT-ECHO" not in response.text and '"input"' not in response.text


def test_connection_test_does_not_save_or_mark_used(client, monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(service, "test_connection", call)
    assert client.post("/settings/model/test", json=config()).status_code == 200
    assert not client.get("/settings/model").json()["configured"]
    assert client.put("/settings/model", json=config()).status_code == 200
    assert client.post("/settings/model/test", json=config(api_key=None)).status_code == 200
    assert client.get("/settings/model").json()["last_used_at"] is None
    assert call.call_args.args[0].api_key == config()["api_key"]


async def test_agent_factory_default_identity_and_personal_models(monkeypatch):
    from app.agent import bot
    default = SimpleNamespace(checkpointer=object(), store=object())
    app = SimpleNamespace(state=SimpleNamespace(async_agent=default))
    async with service.agent_for_connection(app, None) as agent:
        assert agent is default
    captured = {}
    def create_agent(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(bot, "create_agent", create_agent)
    connection = service.ModelConnection(**config())
    async with service.agent_for_connection(app, connection):
        model = captured["model"]
        assert model.model_name == "custom/model:1"
        assert model.openai_api_key.get_secret_value() == config()["api_key"]
        summary = next(m for m in captured["middleware"] if type(m).__name__ == "SummarizationMiddleware")
        assert summary.model is model
        assert captured["checkpointer"] is default.checkpointer
        assert captured["store"] is default.store
    assert bot._model is not model


@pytest.mark.parametrize("path", ["/chat", "/chat/resume", "/chat/stream"])
def test_all_chat_paths_use_same_connection_snapshot(client, monkeypatch, path):
    assert client.put("/settings/model", json=config()).status_code == 200
    seen = []
    agent = AsyncMock()
    agent.ainvoke.return_value = {"messages": [AIMessage(content="ok")]}
    agent.aget_state.return_value = SimpleNamespace(tasks=[], values={"messages": []})
    async def stream(*args, **kwargs):
        yield AIMessage(content="ok"), {"langgraph_node": "model"}
    agent.astream = stream
    @asynccontextmanager
    async def factory(app, connection):
        seen.append(connection)
        yield agent
    monkeypatch.setattr(api_module, "agent_for_connection", factory)
    monkeypatch.setattr(api_module, "_context_for_thread", lambda *a: None)
    monkeypatch.setattr(api_module, "_bind_persona_after_chat", lambda *a: None)
    monkeypatch.setattr(api_module, "_store_assistant_timing", AsyncMock())
    body = {"thread_id": "test", "message": "hi", "decisions": []}
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert len(seen) == 1 and seen[0].api_key == config()["api_key"]
    assert client.get("/settings/model").json()["last_used_at"]
    if path.endswith("stream"):
        assert '"delta": "ok"' in response.text and "[DONE]" in response.text


def test_provider_errors_never_include_secret_details():
    exc = RuntimeError("Bearer test-personal-secret")
    assert "test-personal-secret" not in service.model_error_message(exc)
