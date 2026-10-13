def test_register_and_login(client, register):
    """注册后能登录，错误密码被拒，token 能通过 /auth/me 验证。"""
    user_id, token, username = register()

    # 重复注册同名用户应失败
    r_dup = client.post(
        "/auth/register",
        json={"username": username, "password": "secret123"},
        timeout=120,
    )
    assert r_dup.status_code == 400

    # 正确密码登录
    r = client.post(
        "/auth/login",
        json={"username": username, "password": "secret123"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == username
    assert r.json()["user_id"] == user_id

    # 错误密码登录被拒
    r_bad = client.post(
        "/auth/login",
        json={"username": username, "password": "wrongpass"},
        timeout=120,
    )
    assert r_bad.status_code == 401

    # 带 token 能取到自己的信息
    r_me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    assert r_me.status_code == 200
    assert r_me.json()["username"] == username

    # 不带 token 被拒
    assert client.get("/auth/me", timeout=120).status_code == 401
