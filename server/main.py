"""trmsg - Server Entry Point"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from server.database.db import init_db
from server.api.endpoints import router as api_router
from server.websocket.manager import router as ws_router
from server.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print(f"⚡ trmsg server running on {settings.HOST}:{settings.PORT}")
    yield
    print("👋 trmsg shutting down")

app = FastAPI(title="trmsg", description="Terminal messaging platform", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix="/api/v1")
app.include_router(ws_router)

@app.get("/")
async def root():
    return {"service": "trmsg", "status": "running", "version": "1.0.0", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "trmsg", "version": "1.0.0"}

def run():
    uvicorn.run("server.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)

if __name__ == "__main__":
    run()
