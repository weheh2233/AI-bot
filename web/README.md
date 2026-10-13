# Web demo

完整 Docker 启动方式见项目根目录 `README.md`。

Start the backend first:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --port 8000 --reload
```

In a second terminal, start the web page and same-origin API proxy:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.dev_server:app --port 4173 --reload
```

Open <http://127.0.0.1:4173>. The proxy forwards `/api/*` to the backend at
`BACKEND_URL` (default: `http://127.0.0.1:8000`). Docker Compose sets it to the
backend service address automatically.
