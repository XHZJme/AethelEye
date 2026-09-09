"""
筱和灵眸(AethelEye) - FastAPI主入口

服务启动、路由挂载、CORS配置、静态文件服务
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
import uvicorn
import sys
import asyncio

from app.config import settings
from app.database import init_database, check_admin_exists
from app.routers import auth, users, browser, tasks, webhook, alerts, dashboard, export, logs, recordings, trends, system_settings, llm, engines, plugins, watchdog, mcp_admin
from app.utils.logger import get_logger

# Windows下Playwright依赖可创建子进程的事件循环策略，避免NotImplementedError
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 日志
log = get_logger("system")


# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="面向电商品牌运营团队的全网电商价格智能监控平台",
    docs_url="/docs",  # Swagger文档
    redoc_url="/redoc",  # ReDoc文档
)


# CORS配置：默认只允许本机开发端口，避免服务被浏览器中的任意站点调用。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8686",
        "http://localhost:8686",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 挂载API路由
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(browser.router)
app.include_router(tasks.router)
app.include_router(webhook.router)
app.include_router(alerts.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(logs.router)
app.include_router(recordings.router)
app.include_router(trends.router)
app.include_router(system_settings.router)
app.include_router(llm.router)
app.include_router(engines.router)
app.include_router(plugins.router)
app.include_router(watchdog.router)
app.include_router(mcp_admin.router)


# ===== 启动事件 =====

@app.on_event("startup")
async def startup_event():
    """
    应用启动时执行
    - 初始化数据库
    - 初始化日志系统
    - 启动调度服务
    """
    log.info(
        f"{settings.app_name}服务启动中...",
        data={
            "version": settings.app_version,
            "port": settings.port,
            "data_dir": str(settings.data_dir),
        }
    )

    # 初始化数据库
    init_database()

    # 检查管理员账号状态
    admin_exists = check_admin_exists()
    if not admin_exists:
        log.warning("系统未初始化，请通过 /api/auth/init-admin 创建管理员账号")
    else:
        log.info("系统已初始化，管理员账号存在")

    # 加载外部引擎包
    from app.services.engine_registry import get_engine_registry
    from app.engines.engine_loader import load_and_register_engines
    ext_engines = load_and_register_engines(get_engine_registry())
    if ext_engines:
        log.info(f"已加载外部引擎: {ext_engines}")

    # 启动调度服务
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    scheduler.start()
    scheduler.load_all_tasks()

    # 启动 MCP Server（独立端口8687）
    from app.services.mcp.server import start_mcp_server_background
    start_mcp_server_background()

    # 启动 AI Watchdog（看门狗）
    from app.services.ai_watchdog import get_watchdog
    get_watchdog().start()

    log.info(f"{settings.app_name}服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """
    应用关闭时执行
    - 停止调度服务
    - 停止浏览器管理器
    """
    # 停止 AI Watchdog
    from app.services.ai_watchdog import get_watchdog
    get_watchdog().stop()

    # 停止调度服务
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    scheduler.stop()

    # 停止浏览器管理器
    from app.services.browser_manager import get_browser_manager
    browser_manager = get_browser_manager()
    await browser_manager.stop()

    # 关闭告警服务HTTP客户端
    from app.services.alert_service import get_alert_service
    alert_service = get_alert_service()
    await alert_service.close()

    log.info(f"{settings.app_name}服务关闭")


# ===== 健康检查 =====

@app.get("/api/health")
async def health_check():
    """
    健康检查端点
    """
    return {
        "status": "healthy",
        "version": settings.app_version,
        "timestamp": str(Path(settings.data_dir).stat().st_mtime if settings.data_dir.exists() else "N/A"),
    }


# ===== 系统状态 =====

@app.get("/api/system/info")
async def system_info():
    """
    获取系统信息
    """
    admin_exists = check_admin_exists()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "initialized": admin_exists,
        "port": settings.port,
    }


# ===== 静态文件服务（前端） =====

# 前端构建产物目录
frontend_dist = settings.frontend_dist_dir

if frontend_dist.exists():
    # 挂载静态文件目录
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    # SPA首页路由
    @app.get("/")
    async def serve_index():
        """返回前端首页"""
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse(
            {"error": "前端未构建，请先运行 npm run build"},
            status_code=404
        )

    # SPA路由回退（所有未匹配的路由返回index.html）
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """
        SPA路由回退

        所有未匹配到API路由的请求，返回前端index.html
        让前端路由处理
        """
        # 检查是否是API请求（已在上面处理）
        if path.startswith("api/"):
            return JSONResponse({"error": "API不存在"}, status_code=404)

        # 返回前端index.html
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse(
            {"error": "前端未构建"},
            status_code=404
        )
else:
    # 前端未构建时的提示
    @app.get("/")
    async def no_frontend():
        """前端未构建时的提示"""
        return JSONResponse({
            "message": "前端未构建",
            "hint": "请进入 frontend 目录执行 npm install && npm run build",
            "api_docs": "/docs",
        })


# ===== 异常处理 =====

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理
    """
    log.error(
        f"未捕获异常: {exc}",
        data={
            "path": request.url.path,
            "method": request.method,
            "error": str(exc),
        }
    )
    return JSONResponse(
        {"error": "服务器内部错误"},
        status_code=500
    )


# ===== 启动函数 =====

def main():
    """
    启动服务

    通过 uvicorn 运行 FastAPI
    """
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,  # 生产环境不启用热重载
        log_level="info",
    )


if __name__ == "__main__":
    main()
