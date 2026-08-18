"""API/대시보드 서버 실행: python -m src.serve"""
from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.api:app", host="127.0.0.1", port=8000, reload=False)
