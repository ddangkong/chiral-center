import os, sys
# reload subprocess가 잘못된 CWD로 시작해도 api/core/... 모듈을 찾을 수 있게 보장
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.router import router
from db.neo4j_client import neo4j_client
from core.session import SessionMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await neo4j_client.connect()
    yield
    await neo4j_client.close()


app = FastAPI(title="chiral-center", version="0.1.0", lifespan=lifespan)

# CORS: 쿠키(credentials) 전송 허용이 필요하므로 origin "*" 대신 구체 리스트 사용.
# 개발: Vite proxy를 쓰므로 same-origin이지만 직접 호출도 대비해 localhost 포함.
# 프로덕션에서는 환경변수로 주입 권장.
import os as _os
_cors_origins_env = _os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or [
    "http://localhost:3333",
    "http://127.0.0.1:3333",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 익명 세션 쿠키 미들웨어 — 첫 방문 시 HttpOnly 쿠키 발급
app.add_middleware(SessionMiddleware)

app.include_router(router)


@app.get("/health")
async def health():
    ok = await neo4j_client.ping()
    return {"status": "ok", "neo4j": "ok" if ok else "error"}
