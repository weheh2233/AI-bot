import json
from typing import Literal

from langchain.tools import ToolRuntime, tool

# 语义去重阈值：新记忆与已有记忆相似度 >= 此值时视为同一事实，覆盖旧值。
# 主要去重靠精确 key（save 的 layer 1）；这里只是不同 key 说同一件事时的保险。
# 实测（qwen3.7-text-embedding-flash）：同事实不同说法 0.81~0.87，语义确实高的
# 异事实（如"喜欢篮球"vs"喜欢足球"）也到 0.72。0.92 卡在两者之上，宁可漏并不可误并。
DEDUP_THRESHOLD = 0.92
# 检索返回的最大条数
TOP_K = 10
# 检索相似度下限。实测（qwen3.7-text-embedding-flash）：相关 query 0.65~0.90，
# 无关 query 0.38~0.39。0.5 居中且两边留足余量，避免无关项漏入。
RETRIEVAL_MIN_SCORE = 0.5

# 核心记忆（认知锚点）上限。这类每条都会被全量注入每轮 prompt，必须严格控制条数；
# 满了拒绝新增而非淘汰——锚点不能被悄悄删掉。
MAX_PROFILE = 10
# 普通长期记忆上限，超过按 LRU 淘汰最久未使用的。
MAX_MEMORIES = 50


def _profile_namespace(runtime: ToolRuntime) -> tuple[str, ...]:
    """核心记忆（身份锚点）命名空间：常驻注入，不淘汰。"""
    return ("users", runtime.context.user_id, "profile")


def _memories_namespace(runtime: ToolRuntime) -> tuple[str, ...]:
    """普通长期记忆命名空间：检索命中才注入，超限按 LRU 淘汰。"""
    return ("users", runtime.context.user_id, "memories")


def _evict_memories(store, namespace: tuple[str, ...], limit: int = MAX_MEMORIES) -> None:
    """LRU：条数超过 limit 时，删除最久未被触达的（updated_at 最早）。

    SearchItem 自带 updated_at，store.put 会刷新它。检索命中时回写一次即代表"被使用"，
    所以 updated_at 直接充当 LRU 的访问时间，无需额外字段。
    """
    items = store.search(namespace, limit=limit + 100)
    if len(items) <= limit:
        return
    items.sort(key=lambda it: it.updated_at)          # 最早在前 = 最久未用
    for it in items[: len(items) - limit]:
        store.delete(namespace, it.key)


@tool
def save_user_memory(
    key: str,
    value: str,
    importance: Literal["core", "normal", "transient"],
    runtime: ToolRuntime,
) -> str:
    """保存用户的长期记忆。只在用户意图明确是"要长期记住"时才调用，否则可能只是随口一问。

    key 是记忆名称，必须稳定通用（如"居住地""运动偏好""学习目标"），同一类信息用同一个 key 便于覆盖。
    value 是具体内容。

    importance 决定记忆去向：
      - core：稳定的身份/背景锚点（姓名、职业、母语、长期身份）。永久保留、每轮注入对话、
        不参与淘汰。只用于真正长期稳定的信息，宁缺毋滥，别用来存临时或一般偏好。
      - normal：一般偏好、学习目标等。
      - transient：临时的、一次性的状态（"我今天有点累"）。
    """
    store = runtime.store

    # core → 核心记忆命名空间：满则拒绝，不淘汰
    if importance == "core":
        ns = _profile_namespace(runtime)
        if store.get(ns, key) is None:
            if len(store.search(ns, limit=MAX_PROFILE + 1)) >= MAX_PROFILE:
                return (
                    f"核心记忆已达上限（{MAX_PROFILE} 条），无法新增。"
                    "请先与用户确认哪些核心记忆可以移除或合并。"
                )
        store.put(ns, key, {"key": key, "value": value})
        return f"已保存核心记忆：{key} = {value}"

    # normal / transient → 普通记忆命名空间
    ns = _memories_namespace(runtime)

    # 1) 精确 key 命中：同 key 直接覆盖
    if store.get(ns, key) is not None:
        store.put(ns, key, {"key": key, "value": value})
        _evict_memories(store, ns)
        return f"已更新长期记忆：{key} = {value}"

    # 2) 语义近似：找最相似的一条，够近就覆盖它（合并同一事实的不同说法）
    hits = store.search(ns, query=value, limit=1)
    if hits and hits[0].score is not None and hits[0].score >= DEDUP_THRESHOLD:
        existing_key = hits[0].value.get("key", key)
        store.put(ns, existing_key, {"key": existing_key, "value": value})
        _evict_memories(store, ns)
        return f"已更新长期记忆：{existing_key} = {value}"

    # 3) 新事实，超限由 LRU 淘汰最旧的
    store.put(ns, key, {"key": key, "value": value})
    _evict_memories(store, ns)
    return f"已保存长期记忆：{key} = {value}"


@tool
def get_user_memories(runtime: ToolRuntime, query: str | None = None) -> str:
    """获取当前用户保存过的长期记忆。

    传入 query 时按语义检索最相关的记忆（推荐：把用户当前问题作为 query）；
    不传时返回最近的若干条。
    """
    namespace = _memories_namespace(runtime)
    store = runtime.store

    if query:
        memories = store.search(namespace, query=query, limit=TOP_K)
        memories = [
            m for m in memories if m.score is not None and m.score >= RETRIEVAL_MIN_SCORE
        ]
    else:
        memories = store.search(namespace, limit=TOP_K)

    if not memories:
        return "当前没有相关的长期记忆。"

    # 命中即算"被使用"，回写刷新 updated_at，供 LRU 淘汰排序
    for m in memories:
        store.put(namespace, m.key, m.value)

    result = [
        {"key": item.value.get("key"), "value": item.value.get("value")}
        for item in memories
    ]
    return json.dumps(result, ensure_ascii=False)
