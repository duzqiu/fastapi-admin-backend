"""业务异常定义与全局异常处理器。

服务层只抛出语义化异常（不关心 HTTP），
由这里统一翻译为 HTTP 响应，做到「业务」与「协议」解耦。
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppException(Exception):
    """所有业务异常的基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: int = 40000

    def __init__(self, message: str, *, code: Optional[int] = None, data: Any = None) -> None:
        self.message = message
        self.data = data
        if code is not None:
            self.code = code
        super().__init__(message)


class UnauthorizedError(AppException):
    """未登录 / Token 无效。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = 40100


class ForbiddenError(AppException):
    """已登录但权限不足。"""

    status_code = status.HTTP_403_FORBIDDEN
    code = 40300


class NotFoundError(AppException):
    """资源不存在。"""

    status_code = status.HTTP_404_NOT_FOUND
    code = 40400


class ConflictError(AppException):
    """资源冲突（唯一键重复等）。"""

    status_code = status.HTTP_409_CONFLICT
    code = 40900


class BusinessError(AppException):
    """通用业务规则不满足。"""

    status_code = status.HTTP_400_BAD_REQUEST
    code = 40000


def _payload(code: int, message: str, data: Any = None) -> Dict[str, Any]:
    return {"code": code, "message": message, "data": data}


def register_exception_handlers(app: FastAPI) -> None:
    """把各类异常注册到 FastAPI 应用上。"""

    @app.exception_handler(AppException)
    async def _app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.data),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.status_code * 100, str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 只保留可安全序列化的字段：Pydantic 的 errors() 中 ctx/input 可能包含
        # 无法 JSON 序列化的对象（如自定义校验器抛出的 ValueError），需要过滤掉
        errors = [
            {
                "loc": [str(item) for item in error.get("loc", [])],
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
        first = errors[0] if errors else {}
        location = ".".join(item for item in first.get("loc", []) if item != "body")
        message = f"参数校验失败: {location} {first.get('msg', '')}".strip()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_payload(42200, message, errors),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        from app.core.logging import logger

        logger.exception("未捕获的服务器异常: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_payload(50000, "服务器内部错误"),
        )
