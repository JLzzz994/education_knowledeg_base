"""
认证服务 HTTP 入口模块
承载用户登录/注册/管理等接口，同时提供前端页面服务

启动端口: 8002（由 settings.auth_app_port 控制）
接口清单:
  POST /auth/login       — 用户登录
  POST /auth/register    — 用户注册
  GET  /auth/me          — 获取当前用户信息
  GET  /sessions/{uid}   — 用户会话列表
  GET  /history/user/{uid} — 用户历史消息
  POST /admin/whitelist  — 添加白名单
  DELETE /admin/whitelist/{uid} — 移除白名单
  GET  /admin/users      — 用户列表
  GET  /html             — 登录页面
  GET  /admin            — 管理后台页面
"""
import sys
from mimetypes import guess_type
from pathlib import Path

# 兼容直接以 `python auth_server.py` 方式启动
if __package__ in (None, ""):
    bootstrap_root = Path(__file__).resolve().parents[3]
    if str(bootstrap_root) not in sys.path:
        sys.path.insert(0, str(bootstrap_root))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware

from app.api.routers.auth_router import router as auth_router
from app.infra.config.providers import settings
from app.shared.runtime.logger import PROJECT_ROOT, logger

# ==================== FastAPI 应用实例 ====================
app = FastAPI(
    title=settings.auth_app_name,
    description="企业化 RAG 认证服务，负责用户登录、注册、权限管理。",
    version="0.2.0",
)

# 跨域处理
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载认证路由（包含所有 /auth/*、/admin/*、/sessions/*、/history/* 接口）
app.include_router(auth_router)


# ==================== 页面服务 ====================

@app.get("/html")
def login_html():
    """返回登录/注册页面"""
    html_path = PROJECT_ROOT / "app" / "resources" / "html" / "login.html"
    return FileResponse(
        path=html_path,
        media_type=guess_type(html_path.name)[0],
    )


@app.get("/admin")
def admin_html():
    """返回管理后台页面"""
    html_path = PROJECT_ROOT / "app" / "resources" / "html" / "admin.html"
    return FileResponse(
        path=html_path,
        media_type=guess_type(html_path.name)[0],
    )


# ==================== 启动入口 ====================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.app_host, port=settings.auth_app_port)
