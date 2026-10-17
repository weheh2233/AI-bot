"""LangSmith 配置回归：不访问网络，不上传真实 trace。"""

import asyncio
from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda
from langchain_core.tracers.context import collect_runs

from app.api import _config


def test_chat_config_adds_langsmith_thread_metadata_without_identity_data():
    user = SimpleNamespace(id=7, username="private-name")

    config = _config(
        user,
        "browser-thread",
        run_name="ai-bot-chat-stream",
        tags=["chat", "stream"],
    )

    assert config == {
        "configurable": {"thread_id": "user-7:browser-thread"},
        "metadata": {"thread_id": "user-7:browser-thread", "user_id": "7"},
        "run_name": "ai-bot-chat-stream",
        "tags": ["chat", "stream"],
    }
    assert "private-name" not in str(config)


def test_langchain_receives_run_name_tags_and_metadata():
    async def scenario():
        runnable = RunnableLambda(lambda value: value)
        config = _config(
            SimpleNamespace(id=7),
            "browser-thread",
            run_name="ai-bot-chat-stream",
            tags=["chat", "stream"],
        )
        # collect_runs 只收集本地 callback，不需要 LANGSMITH_API_KEY，也不会联网。
        with collect_runs() as collector:
            assert await runnable.ainvoke("hello", config) == "hello"

        run = collector.traced_runs[0]
        assert run.name == "ai-bot-chat-stream"
        assert run.tags == ["chat", "stream"]
        assert run.extra["metadata"]["thread_id"] == "user-7:browser-thread"

    asyncio.run(scenario())
