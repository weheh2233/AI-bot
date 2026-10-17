import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).parent
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
IDEMPOTENT_METHODS = {"GET", "HEAD"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 复用同一个 AsyncClient。每请求新建客户端会重新建 TCP 连接、不复用 keep-alive，
    # 实测把每个代理请求从 ~15ms 放大到 ~450ms（31x）。
    app.state.http = httpx.AsyncClient(
        timeout=None,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="AI-bot Web Demo", lifespan=lifespan)

app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api(path: str, request: Request):
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    body = await request.body()

    client: httpx.AsyncClient = request.app.state.http

    def build_upstream() -> httpx.Request:
        return client.build_request(
            request.method,
            f"{BACKEND_URL}/{path}",
            params=request.query_params,
            headers=headers,
            content=body,
        )

    try:
        upstream = await client.send(build_upstream(), stream=True)
    except httpx.TransportError as exc:
        # 后端重启后，连接池里缓存的 keep-alive 连接已失效，复用时会在建连或
        # 等响应头阶段抛错。GET/HEAD 换新连接重试一次即可；POST 可能已经到达
        # 上游（例如开始生成），重试会造成重复副作用，只回报 502。
        if request.method not in IDEMPOTENT_METHODS:
            raise HTTPException(status_code=502, detail=f"后端不可用：{exc}") from exc
        try:
            upstream = await client.send(build_upstream(), stream=True)
        except httpx.TransportError as retry_exc:
            raise HTTPException(
                status_code=502, detail=f"后端不可用：{retry_exc}"
            ) from retry_exc

    async def stream_body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            # 只释放这条上游响应；共享客户端留给后续请求复用，不能在这里关掉。
            await upstream.aclose()

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
    }
    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=response_headers,
    )
