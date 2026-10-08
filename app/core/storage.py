"""文件上传存储工具。

统一处理：后缀白名单、大小限制、图片魔术字节校验、落盘与旧文件清理。
业务服务（会员头像、菜品图片）复用这里的函数，避免重复实现。
"""

import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.logging import logger

# 常见图片格式的魔术字节，用于防止「改名的可执行文件」
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def looks_like_image(content: bytes, extension: str) -> bool:
    """通过魔术字节判断文件内容是否为图片。"""
    for signature, _ in _IMAGE_SIGNATURES:
        if content.startswith(signature):
            return True
    # WebP: RIFF....WEBP
    if extension == "webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    return False


def save_image(
    upload: UploadFile,
    *,
    subdir: str,
    prefix: str,
    identifier: str | int = "",
) -> Dict[str, Any]:
    """保存上传的图片并返回访问信息。

    :param subdir:  上传目录下的子目录，如 "avatars" / "dishes"
    :param prefix:  文件名前缀，如 "avatar" / "dish"
    :param identifier: 用于拼接文件名的业务标识（可选）
    """
    filename = upload.filename or ""
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in settings.image_extensions:
        raise BusinessError(f"图片格式不支持，仅允许：{', '.join(settings.image_extensions)}")

    content = upload.file.read()
    max_bytes = settings.IMAGE_MAX_SIZE_MB * 1024 * 1024
    if not content:
        raise BusinessError("上传文件为空")
    if len(content) > max_bytes:
        raise BusinessError(f"图片大小不能超过 {settings.IMAGE_MAX_SIZE_MB} MB")
    if not looks_like_image(content, extension):
        raise BusinessError("文件内容不是有效的图片")

    target_dir = settings.upload_dir / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"_{identifier}" if identifier != "" else ""
    new_filename = f"{prefix}{suffix}_{uuid.uuid4().hex[:12]}.{extension}"
    (target_dir / new_filename).write_bytes(content)

    return {
        "url": f"{settings.upload_url_prefix}/{subdir}/{new_filename}",
        "filename": new_filename,
        "size": len(content),
    }


def remove_upload(url: str) -> None:
    """删除由本服务上传的文件（外部链接会被忽略），并做路径穿越防护。"""
    if not url or not url.startswith(settings.upload_url_prefix):
        return

    relative = url[len(settings.upload_url_prefix):].lstrip("/")
    try:
        target = (settings.upload_dir / relative).resolve()
        # 必须位于上传目录之内
        if settings.upload_dir in target.parents and target.is_file():
            target.unlink()
    except OSError as exc:  # pragma: no cover - 磁盘异常
        logger.warning("删除上传文件失败: %s (%s)", url, exc)


__all__ = ["looks_like_image", "save_image", "remove_upload"]
