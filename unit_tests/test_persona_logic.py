from types import SimpleNamespace
from unittest.mock import Mock

from app.api import _persona_for_thread


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_explicit_persona_wins_over_account_default_for_new_thread():
    selected = SimpleNamespace(
        id=1,
        name="显式选择",
        role_definition="role",
        tone="tone",
        style_rules="",
        constraints="",
    )
    db = Mock()
    db.execute.side_effect = [Result(None), Result(selected)]
    user = SimpleNamespace(id=7, default_persona_id=2)

    assert _persona_for_thread(db, user, "new-thread", preferred_persona_id=1) == (
        "显式选择",
        "角色定位：role\n语气：tone",
    )
    assert db.execute.call_count == 2


def test_existing_conversation_persona_wins_over_account_default():
    selected = SimpleNamespace(
        id=1,
        name="会话角色",
        role_definition="role",
        tone="tone",
        style_rules="",
        constraints="",
    )
    db = Mock()
    db.execute.side_effect = [
        Result(SimpleNamespace(persona_id=1, persona_snapshot=None)),
        Result(selected),
    ]
    user = SimpleNamespace(id=7, default_persona_id=2)

    assert _persona_for_thread(db, user, "existing-thread") == (
        "会话角色",
        "角色定位：role\n语气：tone",
    )
    assert db.execute.call_count == 2


def test_conversation_prompt_uses_saved_snapshot():
    db = Mock()
    db.execute.return_value = Result(
        SimpleNamespace(
            persona_id=1,
            persona_snapshot={"name": "旧角色名", "prompt": "旧角色提示词"},
        )
    )
    user = SimpleNamespace(id=7, default_persona_id=2)

    assert _persona_for_thread(db, user, "snapshotted-thread") == (
        "旧角色名",
        "旧角色提示词",
    )
    assert db.execute.call_count == 1
