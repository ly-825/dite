from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.profile import router as profile_router
from app.core.config import settings
from app.services.chat_service import chat_service


FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def serve_frontend_asset(full_path: str = ""):
    """优先返回前端静态资源或 SPA 入口；无前端产物时退回 API 说明。"""
    if not FRONTEND_DIST_DIR.exists():
        return {
            "message": "Diet Delushan API 启动成功",
            "docs": "/docs",
            "health": "/api/health",
        }

    requested_path = FRONTEND_DIST_DIR / full_path
    if full_path and requested_path.is_file():
        return FileResponse(requested_path)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return {
        "message": "Diet Delushan API 启动成功",
        "docs": "/docs",
        "health": "/api/health",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用启动时加载核心体检报告。"""
    chat_service.load_persisted_report()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# 配置前后端分离开发时的跨域访问。j
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(profile_router)


@app.get("/", include_in_schema=False)
def read_root():
    """后端根路径说明。"""
    return serve_frontend_asset()


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """健康检查接口。"""
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    """生产环境下由后端直接托管前端静态文件与 SPA 入口。"""
    return serve_frontend_asset(full_path)



if __name__ == "__main__":

    # 这里使用 uvicorn 以便支持自动重载等功能
    import uvicorn

    # 在 PowerShell 中可以使用：py -3 main.py 来启动
    uvicorn.run("main:app", host="0.0.0.0", port=8037, reload=False)
