import uuid


def test_same_user_resumes_session(chat, register):
    """同一用户在同一 thread_id 的多轮对话中，能记住前文内容。"""
    _, token, _ = register()
    tid = f"t-{uuid.uuid4().hex[:8]}"

    chat(token, "我们玩角色扮演，在这个对话里你称呼我为「队长」。", tid)
    reply = chat(token, "在这个对话里，你该称呼我什么？", tid)

    assert "队长" in reply


def test_different_users_isolated(chat, register):
    """不同用户用相同 thread_id，不能读到对方的会话内容。"""
    _, token_a, _ = register()
    _, token_b, _ = register()
    shared_tid = f"t-{uuid.uuid4().hex[:8]}"
    secret = f"紫罗兰{uuid.uuid4().hex[:4]}"

    chat(token_a, f"记住一个内部代号：{secret}", shared_tid)
    reply_b = chat(token_b, "刚才那个内部代号是什么？", shared_tid)

    # B 看不到 A 的会话；若泄露，secret 会出现在回复里
    assert secret not in reply_b


def test_long_term_memory_across_threads(chat, register):
    """同一用户长期记忆能跨越不同 thread_id 读取。"""
    _, token, _ = register()
    job = f"我的职业是医生{uuid.uuid4().hex[:4]}"

    chat(token, f"请记住：{job}", f"t-{uuid.uuid4().hex[:8]}")
    reply = chat(token, "我的职业是什么？", f"t-{uuid.uuid4().hex[:8]}")

    assert "医生" in reply


def test_conversation_history_can_be_loaded_and_resumed(client, chat, register):
    """历史接口只返回当前用户会话，详情可加载，原 thread_id 可继续对话。"""
    _, token, _ = register()
    _, other_token, _ = register()
    thread_id = f"history-{uuid.uuid4().hex[:8]}"
    secret = f"青铜钟{uuid.uuid4().hex[:4]}"
    headers = {"Authorization": f"Bearer {token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    chat(token, f"本次对话的临时口令是「{secret}」，只在当前会话记住它。", thread_id)

    history = client.get("/conversations", headers=headers, timeout=120)
    assert history.status_code == 200, history.text
    item = next(row for row in history.json() if row["thread_id"] == thread_id)
    assert secret in item["title"]
    assert item["message_count"] >= 2

    detail = client.get(f"/conversations/{thread_id}", headers=headers, timeout=120)
    assert detail.status_code == 200, detail.text
    assert any(secret in message["content"] for message in detail.json()["messages"])

    assert client.get(
        f"/conversations/{thread_id}", headers=other_headers, timeout=120
    ).status_code == 404

    reply = chat(token, "本次对话的临时口令是什么？", thread_id)
    assert secret in reply


def test_conversation_title_can_be_updated_and_isolated(client, chat, register):
    """会话标题可修改，且不能修改另一个用户的会话。"""
    _, token, _ = register()
    _, other_token, _ = register()
    thread_id = f"rename-{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    chat(token, "这是一个用于测试标题修改的会话。", thread_id)
    response = client.patch(
        f"/conversations/{thread_id}",
        json={"title": "LangChain 复习计划"},
        headers=headers,
        timeout=120,
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "LangChain 复习计划"

    detail = client.get(f"/conversations/{thread_id}", headers=headers, timeout=120)
    assert detail.json()["title"] == "LangChain 复习计划"
    assert client.patch(
        f"/conversations/{thread_id}",
        json={"title": "越权修改"},
        headers=other_headers,
        timeout=120,
    ).status_code == 404
