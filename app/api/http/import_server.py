"""
导入服务 FastAPI 应用入口
提供文件上传、导入进度查询等接口
启动命令: uvicorn app.api.http.import_server:app --host 0.0.0.0 --port 8000
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.routers.import_router import router as import_router
from app.shared.config.settings_config import settings
from app.shared.utils.path_util import PROJECT_ROOT

app = FastAPI(title=settings.import_app_name)

# ==================== CORS 中间件 ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 挂载导入路由 ====================
app.include_router(import_router)


# ==================== 公开页面 & 健康检查 ====================

@app.get("/html")
def get_import_page():
    """返回导入页面 HTML"""
    html_path = os.path.join(PROJECT_ROOT, "docs", "html", "import.html")
    if not os.path.exists(html_path):
        return JSONResponse(status_code=404, content={"detail": "import.html 不存在"})
    return FileResponse(html_path, media_type="text/html")


@app.get("/health")
def health_check():
    """健康检查接口"""
    return {"alive": "yes"}


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.http.import_server:app",
        host=settings.app_host,
        port=settings.import_app_port,
        reload=settings.app_env == "dev",
    )
