"""
认证服务 FastAPI 应用入口
提供用户登录、注册、Token 刷新、白名单管理、会话列表、历史记录查询等接口
启动命令: uvicorn app.api.http.auth_server:app --host 0.0.0.0 --port 8002
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.routers.auth_router import router as auth_router
from app.shared.config.settings_config import settings
from app.shared.utils.path_util import PROJECT_ROOT

app = FastAPI(title=settings.auth_app_name)

# ==================== CORS 中间件 ====================
# 允许前端跨域访问，支持配置多域名（逗号分隔）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 挂载认证路由 ====================
app.include_router(auth_router)


# ==================== 公开页面 & 健康检查 ====================

@app.get("/html")
def get_login_page():
    """返回登录页面 HTML"""
    html_path = os.path.join(PROJECT_ROOT, "docs", "html", "login.html")
    if not os.path.exists(html_path):
        return JSONResponse(status_code=404, content={"detail": "login.html 不存在"})
    return FileResponse(html_path, media_type="text/html")


@app.get("/health")
def health_check():
    """健康检查接口"""
    return {"alive": "yes"}


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.http.auth_server:app",
        host=settings.app_host,
        port=settings.auth_app_port,
        reload=settings.app_env == "dev",
    )
