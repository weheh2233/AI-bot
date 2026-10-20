
# 后端改动清单：app/api.py

## 改动 1：导入 field_validator（文件顶部，约第 10 行附近）
找到 pydantic 导入行，添加 field_validator：
```python
from pydantic import BaseModel, field_validator
```

## 改动 2：修改 ChatRequest 类（第 65-70 行）
```python
class ChatRequest(BaseModel):
    message: str
    images: list[str] = []  # base64 data URLs
    thread_id: str
    persona_id: int | None = None
    turn_id: str | None = None
    regenerate: bool = False
    
    @field_validator('images')
    @classmethod
    def validate_images(cls, v):
        from app.config import settings
        if len(v) > settings.max_images_per_request:
            raise ValueError(f'最多上传 {settings.max_images_per_request} 张图片')
        for img in v:
            if not img.startswith('data:image/'):
                raise ValueError('图片格式错误，需要 data URL')
        return v
```

## 改动 3：修改 ConversationMessage 类（第 78-82 行）
```python
class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    images: list[str] | None = None  # 新增
    timestamp: datetime | None = None
    elapsed: float | None = None
```

## 改动 4：新增辅助函数（第 341 行 _content_text 函数之后）
```python
def _extract_images(content) -> list[str]:
    """从内容块中提取图片 data URLs。"""
    if not isinstance(content, list):
        return []
    
    images = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image_url":
            url = block.get("image_url", {}).get("url")
            if url:
                images.append(url)
    return images


def _count_images_in_state(state) -> int:
    """统计当前 checkpoint 中用户消息的图片总数。"""
    count = 0
    for msg in state.values.get("messages", []):
        if isinstance(msg, HumanMessage):
            count += len(_extract_images(msg.content))
    return count
```

## 改动 5：修改 _conversation_messages_from_list 函数（第 365-390 行）
在构建 ConversationMessage 时：
```python
# 原代码约在 378-387 行
content = _content_text(message.content)
images = _extract_images(message.content) if role == "user" else None

# 至少要有文本或图片之一
if content or images:
    messages.append(
        ConversationMessage(
            role=role,
            content=content or "[图片]",  # 纯图片消息显示占位符
            images=images,
            timestamp=timestamp,
            elapsed=elapsed,
        )
    )
```

## 改动 6：修改 _timed_user_message 函数（第 477-481 行）
```python
def _timed_user_message(content: str, images: list[str] | None = None) -> HumanMessage:
    """构建带时间戳的用户消息，支持文本 + 图片。"""
    if not images:
        message_content = content
    else:
        # 构建内容块数组：文本在前，图片在后
        message_content = [{"type": "text", "text": content}]
        for img_url in images:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": img_url}
            })
    
    return HumanMessage(
        content=message_content,
        additional_kwargs={"timestamp": datetime.now(timezone.utc).isoformat()},
    )
```

## 改动 7：修改 /chat 接口（约第 1092 行，在 payload 构建之前）
```python
# 检查图片配额
if req.images:
    snapshot = await agent.aget_state(config)
    current_count = _count_images_in_state(snapshot)
    if current_count + len(req.images) > settings.max_images_per_thread:
        raise HTTPException(
            422,
            f"本会话最多 {settings.max_images_per_thread} 张图片，当前已有 {current_count} 张，请新建会话"
        )

payload = {"messages": [_timed_user_message(req.message, req.images)]}
```

## 改动 8：修改 /chat/stream 接口（约第 1197 行，produce 函数内）
```python
async def produce(agent):
    # 检查配额（重新生成时不检查，因为不带新图）
    if not req.regenerate and req.images:
        snapshot = await agent.aget_state(config)
        current_count = _count_images_in_state(snapshot)
        if current_count + len(req.images) > settings.max_images_per_thread:
            raise HTTPException(
                422,
                f"本会话最多 {settings.max_images_per_thread} 张图片，当前已有 {current_count} 张"
            )
    
    message = req.message
    if req.regenerate:
        message = await _prepare_regeneration(agent, config)
    payload = {"messages": [_timed_user_message(message, req.images if not req.regenerate else None)]}
    # ... 后续代码不变
```

---

# 检查清单

1. ✅ 导入 field_validator
2. ⏳ ChatRequest 添加 images 字段和 validator
3. ⏳ ConversationMessage 添加 images 字段
4. ⏳ 新增 _extract_images 和 _count_images_in_state
5. ⏳ _conversation_messages_from_list 支持图片
6. ⏳ _timed_user_message 支持图片
7. ⏳ /chat 接口检查配额
8. ⏳ /chat/stream 接口检查配额

---

# 关键导入检查
- `from pydantic import BaseModel, field_validator`
- `from langchain_core.messages import HumanMessage` (已存在)
- `from app.config import settings` (在 validator 内部导入)
