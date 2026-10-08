"""应用入口：组装 FastAPI 实例。

职责只有「装配」：
    - 注册中间件（CORS、请求日志）
    - 注册全局异常处理器
    - 挂载 v1 路由
    - 应用生命周期（启动时初始化数据库）
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import logger, setup_logging
from app.db.init_db import init_db
from app.middlewares.request_log import RequestLogMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用启动 / 关闭钩子。"""
    setup_logging()
    logger.info("正在启动 %s v%s ...", settings.PROJECT_NAME, settings.VERSION)
    try:
        init_db()
    except Exception as exc:  # pragma: no cover - 数据库不可用时仍允许服务启动查看报错
        logger.error("数据库初始化失败: %s", exc)
        raise
    logger.info("服务已就绪，接口文档: http://127.0.0.1:%s/docs", settings.PORT)
    yield
    logger.info("服务已关闭")


def create_app() -> FastAPI:
    """工厂函数：创建并配置 FastAPI 应用。"""
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        lifespan=lifespan,
    )

    # 注意：add_middleware 后添加者位于外层，CORS 必须在最外层才能处理预检请求
    application.add_middleware(RequestLogMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-Process-Time"],
    )

    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # 挂载上传目录（会员头像等）。挂在 API 前缀下，前端 /api 代理与 Nginx 反向代理可直接复用
    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    application.mount(
        settings.upload_url_prefix,
        StaticFiles(directory=str(upload_dir)),
        name="uploads",
    )

    # 挂载内置静态资源（默认头像等）。同样挂在 API 前缀下，便于复用 /api 代理规则
    assets_dir = Path(__file__).resolve().parent / "static"
    assets_dir.mkdir(parents=True, exist_ok=True)
    application.mount(
        f"{settings.API_V1_PREFIX}/assets",
        StaticFiles(directory=str(assets_dir)),
        name="assets",
    )

    @application.get("/", tags=["系统"], summary="服务根路径")
    def root() -> dict:
        return {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "docs": "/docs",
            "api_prefix": settings.API_V1_PREFIX,
        }

    return application


app = create_app()
