FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --upgrade pip && \
    pip install "fastapi>=0.115,<1.0" "httpx>=0.28,<1.0" "uvicorn[standard]>=0.34,<1.0"

COPY web ./web

EXPOSE 4173

CMD ["uvicorn", "web.dev_server:app", "--host", "0.0.0.0", "--port", "4173"]
