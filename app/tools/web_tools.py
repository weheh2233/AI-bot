import httpx
import trafilatura
from langchain.tools import tool

from app.config import settings

# 搜索结果条数与每条正文截断长度（新闻/摘要本身短，够用即可）
SEARCH_TOP_N = 5
SEARCH_SNIPPET_CHARS = 300
# 网页正文截断长度。正文要进模型 context，不设上限会撑爆窗口。
PAGE_MAX_CHARS = 4000
HTTP_TIMEOUT = 20.0
_UA = "Mozilla/5.0 (compatible; AI-bot/1.0)"

_ZHIPU_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
# search_std 只给聚合摘要（link 为空），search_pro 才返回可抓取的原始链接
_SEARCH_ENGINE = "search_pro"


@tool
def web_search(query: str) -> str:
    """联网搜索最新信息，返回若干条结果的标题、链接和摘要。

    用于查询模型训练数据之外的实时信息（新闻、最新文档、当前事件）。
    需要网页正文时，再用返回的链接调用 fetch_webpage。
    """
    if not settings.zhipuai_api_key:
        return "未配置 ZHIPUAI_API_KEY，无法联网搜索。"

    try:
        resp = httpx.post(
            _ZHIPU_SEARCH_URL,
            headers={"Authorization": f"Bearer {settings.zhipuai_api_key}"},
            json={"search_engine": _SEARCH_ENGINE, "search_query": query},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"联网搜索失败：{e}"

    results = resp.json().get("search_result", [])
    if not results:
        return f"没有搜到「{query}」的相关结果。"

    lines = []
    for i, item in enumerate(results[:SEARCH_TOP_N], 1):
        title = item.get("title", "")
        link = item.get("link", "")
        content = (item.get("content", "") or "")[:SEARCH_SNIPPET_CHARS]
        lines.append(f"{i}. {title}\n   {link}\n   {content}")
    return "\n".join(lines)


@tool
def fetch_webpage(url: str) -> str:
    """抓取一个网页链接的正文内容（已去除导航、广告等噪声）。

    通常配合 web_search 使用：先搜索拿到链接，再抓取具体页面正文。
    返回正文文本，由你据此总结或回答用户。
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _UA},
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"抓取网页失败：{e}"

    text = trafilatura.extract(resp.text)
    if not text:
        return f"未能从该页面提取到正文：{url}"

    if len(text) > PAGE_MAX_CHARS:
        text = text[:PAGE_MAX_CHARS] + "\n...[内容过长已截断]"
    return text
