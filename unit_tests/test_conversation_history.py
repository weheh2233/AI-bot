from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from app.api import _conversation_messages_from_history


class _FakeAgent:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def get_state_history(self, config):
        return iter(self._snapshots)


def _snapshot(*messages):
    return SimpleNamespace(values={"messages": list(messages)})


def test_summarization_history_keeps_messages_removed_from_latest_state():
    first_user = HumanMessage("第一轮问题", id="user-1")
    first_answer = AIMessage("第一轮回答", id="assistant-1")
    second_user = HumanMessage("第二轮问题", id="user-2")
    second_answer = AIMessage("第二轮回答", id="assistant-2")
    summary = HumanMessage(
        "历史摘要", id="summary-1", additional_kwargs={"lc_source": "summarization"}
    )

    # get_state_history 按最新到最旧返回。
    agent = _FakeAgent(
        [
            _snapshot(summary, second_user, second_answer),
            _snapshot(first_user, first_answer, second_user, second_answer),
            _snapshot(first_user, first_answer, second_user),
            _snapshot(first_user, first_answer),
        ]
    )

    messages = _conversation_messages_from_history(
        agent,
        {"configurable": {"thread_id": "test"}},
        _snapshot(summary, second_user, second_answer),
    )

    assert [(message.role, message.content) for message in messages] == [
        ("user", "第一轮问题"),
        ("assistant", "第一轮回答"),
        ("user", "第二轮问题"),
        ("assistant", "第二轮回答"),
    ]


def test_explicitly_removed_messages_are_not_restored():
    first_user = HumanMessage("保留的问题", id="user-1")
    first_answer = AIMessage("保留的回答", id="assistant-1")
    removed_user = HumanMessage("被重新生成的问题", id="user-2")
    removed_answer = AIMessage("旧回答", id="assistant-2")
    regenerated_answer = AIMessage("新回答", id="assistant-3")
    summary = HumanMessage(
        "历史摘要", id="summary-1", additional_kwargs={"lc_source": "summarization"}
    )

    agent = _FakeAgent(
        [
            _snapshot(summary, first_user, first_answer, regenerated_answer),
            _snapshot(summary, first_user, first_answer, removed_user, removed_answer),
            _snapshot(first_user, first_answer, removed_user, removed_answer),
        ]
    )

    messages = _conversation_messages_from_history(
        agent,
        {"configurable": {"thread_id": "test"}},
        _snapshot(summary, first_user, first_answer, regenerated_answer),
    )

    assert [(message.role, message.content) for message in messages] == [
        ("user", "保留的问题"),
        ("assistant", "保留的回答"),
        ("assistant", "新回答"),
    ]
