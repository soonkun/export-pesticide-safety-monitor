"""API/대시보드/관제 서버 실행: python -m src.serve

기본은 127.0.0.1 바인딩 — 외부 공개는 Cloudflare Tunnel(cloudflared)이 담당한다.
직접 노출이 필요하면 HOST=0.0.0.0 을 .env 에 설정.
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.api:app", host=os.getenv("HOST", "127.0.0.1"),
                port=int(os.getenv("PORT", "8000")), reload=False)
