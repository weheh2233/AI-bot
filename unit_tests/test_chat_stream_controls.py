import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

from app.api import _prepare_regeneration
from app.chat_streams import CANCELLED_EVENT, ChatRun, ChatStreamRegistry


def test_pause_resume_reports_last_sent_cursor():
    async def scenario():
        registry = ChatStreamRegistry()
        run = ChatRun(user_id=1, thread_id="thread", turn_id="turn")
        registry.register(run)
        lock = await registry.activate(run)
        run.last_sent_seq = 7

        paused = registry.pause(run)
        assert paused == {"status": "paused", "last_sent_seq": 7}
        assert not run.resumed.is_set()

        resumed = registry.resume(run)
        assert resumed == {"status": "running", "last_sent_seq": 7}
        assert run.resumed.is_set()
        registry.finish(run, lock)

    asyncio.run(scenario())


def test_cancel_discards_buffer_and_wakes_stream_consumer():
    async def scenario():
        registry = ChatStreamRegistry()
        run = ChatRun(user_id=1, thread_id="thread", turn_id="turn")
        registry.register(run)
        lock = await registry.activate(run)
        run.queue.put_nowait({"delta": "not sent yet"})
        registry.pause(run)

        result = registry.cancel(run)

        assert result["status"] == "cancelled"
        assert run.resumed.is_set()
        assert run.queue.get_nowait() is CANCELLED_EVENT
        registry.finish(run, lock)

    asyncio.run(scenario())


def test_regeneration_removes_last_user_turn_before_replaying():
    user_message = HumanMessage(content="question", id="user-1")
    assistant_message = AIMessage(content="answer", id="assistant-1")
    snapshot = SimpleNamespace(values={"messages": [user_message, assistant_message]})
    agent = AsyncMock()
    agent.aget_state.return_value = snapshot

    assert asyncio.run(_prepare_regeneration(agent, {})) == "question"
    removed = agent.aupdate_state.call_args.args[1]["messages"]
    assert [message.id for message in removed] == ["user-1", "assistant-1"]
    assert all(isinstance(message, RemoveMessage) for message in removed)


def test_regeneration_refuses_to_repeat_memory_write_side_effect():
    messages = [
        HumanMessage(content="remember this", id="user-1"),
        AIMessage(content="", id="assistant-tool", tool_calls=[
            {"name": "save_user_memory", "args": {}, "id": "call-1", "type": "tool_call"}
        ]),
        ToolMessage(content="saved", name="save_user_memory", tool_call_id="call-1", id="tool-1"),
        AIMessage(content="done", id="assistant-2"),
    ]
    agent = AsyncMock()
    agent.aget_state.return_value = SimpleNamespace(values={"messages": messages})

    with pytest.raises(HTTPException) as error:
        asyncio.run(_prepare_regeneration(agent, {}))

    assert error.value.status_code == 409
    agent.aupdate_state.assert_not_called()
