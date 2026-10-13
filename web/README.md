# Web demo

Start the backend first:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api:app --port 8000 --reload
```

In a second terminal, start the web page and same-origin API proxy:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.dev_server:app --port 4173 --reload
```

Open <http://127.0.0.1:4173>. The proxy forwards `/api/*` to the backend at `127.0.0.1:8000`; change `BACKEND_URL` in `dev_server.py` if the backend uses another address.
