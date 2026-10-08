"""请求日志中间件：记录每个请求的方法、路径、状态码与耗时。"""

import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import logger


class RequestLogMiddleware(BaseHTTPMiddleware):
    """在响应头中返回 X-Request-Id，并按耗时输出访问日志。"""

    SKIP_PATHS = {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        # 文档页与静态资源（上传的头像等）不记录访问日志，避免刷屏
        if path in self.SKIP_PATHS or path.startswith(settings.upload_url_prefix):
            return await call_next(request)

        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            cost = (time.perf_counter() - started) * 1000
            logger.exception(
                "[%s] %s %s 处理异常 耗时=%.2fms", request_id, request.method, request.url.path, cost
            )
            raise

        cost = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Process-Time"] = f"{cost:.2f}ms"
        logger.info(
            "[%s] %s %s -> %s 耗时=%.2fms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            cost,
        )
        return response
