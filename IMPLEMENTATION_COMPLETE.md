# 图片上传功能 - 实施完成

**时间：** 2026-10-20 17:17
**状态：** ✅ 后端 + 前端全部完成

---

## 已完成的改动

### 后端（app/api.py + app/config.py）

1. ✅ **配置项**（app/config.py）
   - `max_images_per_request = 5`
   - `max_images_per_thread = 20`

2. ✅ **导入 field_validator**
   - `from pydantic import BaseModel, field_validator`

3. ✅ **ChatRequest 类**（第 65-82 行）
   - 添加 `images: list[str] = []` 字段
   - 添加 `@field_validator('images')` 校验器

4. ✅ **ConversationMessage 类**（第 90-95 行）
   - 添加 `images: list[str] | None = None` 字段

5. ✅ **辅助函数**（第 370 行后）
   - `_extract_images(content)` - 从内容块提取图片
   - `_count_images_in_state(state)` - 统计会话图片数

6. ✅ **_conversation_messages_from_list**（第 418 行）
   - 提取用户消息中的图片
   - 在 ConversationMessage 中包含 images
   - 纯图片消息显示 "[图片]"

7. ✅ **_timed_user_message**（第 515 行）
   - 添加 `images` 参数
   - 构建内容块数组（文本 + image_url）

8. ✅ **/chat 接口**（第 1087 行）
   - 检查图片配额
   - 传递 images 到 _timed_user_message

9. ✅ **/chat/stream 接口**（第 1199 行）
   - 检查配额（重新生成时跳过）
   - 条件传递 images

---

### 前端（uniapp）

1. ✅ **utils/image-compress.ts**（新建）
   - `compressImage()` - 单张压缩
   - `compressImages()` - 批量压缩
   - 长边 1280px，质量 0.8

2. ✅ **api/index.ts**
   - `ChatMessage.images?: string[]`
   - `ChatRequestPayload.images?: string[]`

3. ✅ **stores/chat.ts**
   - `UiMessage.images?: string[]`
   - `sendMessage(text, images)` 方法签名
   - API payload 传递 images

4. ✅ **components/MessageItem.vue**
   - 添加 `images?: string[]` prop
   - 渲染图片列表
   - `previewImage()` 函数
   - 图片样式

5. ✅ **pages/index/index.vue**
   - 导入 `compressImages`
   - `selectedImages` 状态
   - `pickImages()` 选图函数
   - `removeImage()` 删除函数
   - 修改 `sendMessage()` 传递 images
   - 隐藏 canvas（压缩用）
   - 图片预览区 UI
   - 📎 选图按钮
   - 样式

---

## 测试清单

### 基础功能
- [ ] 点击 📎 按钮，能选择图片
- [ ] 选择后显示缩略图预览
- [ ] 点击预览图的 ✕ 能删除
- [ ] 发送纯文本消息（不带图）正常
- [ ] 发送 1 张图 + 文本，模型能识别
- [ ] 发送多张图（2-5 张），模型能识别
- [ ] 压缩后图片大小约 150-250KB

### 限制和校验
- [ ] 单次选择超过 5 张，前端提示
- [ ] 单次发送 5 张（上限）成功
- [ ] 会话累积 20 张后，第 21 张被后端拒绝（HTTP 422）
- [ ] 错误提示友好

### 历史和多轮
- [ ] 刷新页面，历史消息中的图片仍可见
- [ ] 点击历史图片能预览（`uni.previewImage`）
- [ ] 下一轮追问图片内容，模型能回答（证明在上下文）
- [ ] 重新生成（regenerate）不重复发送图片

### 边界情况
- [ ] 纯图片消息（无文本）显示 "[图片]"
- [ ] 图片格式错误（非 data URL）被后端拒绝
- [ ] 取消选图不报错

---

## 注意事项

1. **DeepSeek API 兼容性**
   - 使用 OpenAI Vision 格式：`content: [{type:"text"},{type:"image_url"}]`
   - LangChain `HumanMessage` 自动转换

2. **存储**
   - 图片 base64 存入 PostgreSQL JSONB（checkpoint）
   - 单张约 200KB base64 → 267KB 文本
   - 20 张约 5MB

3. **性能**
   - 前端压缩减少传输
   - 后端不做额外处理，直接传给模型
   - checkpoint 读写略慢（JSONB 大小）

4. **平台差异**
   - uni-app canvas API 在小程序/App 有细微差异
   - 如遇问题可能需要 `#ifdef` 调整

---

## 下一步

建议按测试清单逐项验证。如遇问题：
1. 检查浏览器/小程序控制台
2. 检查后端日志（FastAPI 会打印 422 错误详情）
3. 检查 PostgreSQL checkpoint 数据（`SELECT * FROM checkpoints LIMIT 1`）

启动命令：
```bash
# 后端
cd D:\Pycharm\Pycharm_Projects\AI-bot
uvicorn app.api:app --reload

# 前端
cd uniapp-frontend/ai-bot-uniapp
npm run dev:h5  # 或 dev:mp-weixin
```
