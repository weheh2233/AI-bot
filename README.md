# AI-bot

基于 LangChain、LangGraph、PostgreSQL/pgvector 的智能学习助手。

## Docker 启动

1. 复制 `.env.example` 为 `.env`，至少填写 `DEEPSEEK_API_KEY` 和
   `DASHSCOPE_API_KEY`。需要联网搜索时再填写 `ZHIPUAI_API_KEY`，并把
   `JWT_SECRET_KEY` 换成长度不少于 32 个字符的随机值。
2. 构建并启动全部服务：

   ```powershell
   docker compose up -d --build
   ```

3. 打开前端：<http://127.0.0.1:4173>

后端接口文档位于 <http://127.0.0.1:8000/docs>。首次启动时后端会在
PostgreSQL 健康后自动创建 `vector` 扩展、业务表、LangGraph checkpoint
表和长期记忆表。

查看状态与日志：

```powershell
docker compose ps
docker compose logs -f backend frontend
```

停止服务但保留数据库数据：

```powershell
docker compose down
```

需要连数据库数据一起清除时，显式执行 `docker compose down -v`。
