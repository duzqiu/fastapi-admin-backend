"""文件上传存储工具。

统一处理：后缀白名单、大小限制、图片魔术字节校验、落盘与旧文件清理。
业务服务（会员头像、菜品图片）复用这里的函数，避免重复实现。

**iPhone 的 HEIC / HEIF**：iOS 相机默认出这个格式，后缀白名单放行、识别也放行，
但**落盘前统一转成 JPEG** —— 浏览器（后台前端 `<img>`）和 Flutter（App 的 `ft.Image`）
都渲染不了 HEIC，直接存下来等于「传上去了但哪儿都看不见」。
"""

import io
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

# HEIC / HEIF 的后缀（比较前先 `Path(...).suffix.lower()`）
HEIF_EXTENSIONS = ("heic", "heif")
# HEIF 属于 ISO-BMFF：第 4~8 字节是 `ftyp`，紧跟 4 字节品牌代号。iOS 常见的是
# heic / heix（HEVC 主图）、mif1 / msf1（HEIF 容器）。
_HEIF_BRANDS = (
    b"heic",
    b"heix",
    b"hevc",
    b"hevx",
    b"heim",
    b"heis",
    b"hevm",
    b"hevs",
    b"mif1",
    b"msf1",
)
# 转 JPEG 的起始 / 保底质量（转完还超大小上限就再降一档）。
_JPEG_QUALITIES = (88, 75, 60)


def looks_like_image(content: bytes, extension: str) -> bool:
    """通过魔术字节判断文件内容是否为图片。"""
    for signature, _ in _IMAGE_SIGNATURES:
        if content.startswith(signature):
            return True
    # WebP: RIFF....WEBP
    if extension == "webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return True
    # HEIC / HEIF（iPhone 相机的默认格式）
    if len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in _HEIF_BRANDS:
        return True
    return False


def is_heif(content: bytes) -> bool:
    """是不是 HEIC / HEIF —— 看**内容**，避免只改了后缀的假文件。"""
    return (
        len(content) >= 12
        and content[4:8] == b"ftyp"
        and content[8:12] in _HEIF_BRANDS
    )


def heif_to_jpeg(content: bytes, max_bytes: int = 0) -> bytes:
    """把 HEIC / HEIF 转成 JPEG 字节。

    `max_bytes` 不为 0 时会逐档降质量，尽量压到上限之内。转不了（没装
    `pillow-heif`、文件损坏）一律抛 `BusinessError`，让接口给出人话。
    """
    try:
        import pillow_heif
        from PIL import Image, ImageOps
    except ImportError as error:  # pragma: no cover - 依赖没装
        raise BusinessError(
            "服务器未启用 HEIC 支持（缺 pillow-heif），请改用 JPG / PNG 上传"
        ) from error

    pillow_heif.register_heif_opener()
    try:
        with Image.open(io.BytesIO(content)) as image:
            # 手机照片靠 EXIF 记旋转方向，转码时先正过来，否则存下来是躺着的。
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            data = b""
            for quality in _JPEG_QUALITIES:
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                data = buffer.getvalue()
                if not max_bytes or len(data) <= max_bytes:
                    break
            return data
    except Exception as error:  # noqa: BLE001 - 解码失败也当业务错误往上抛
        raise BusinessError("HEIC 图片解析失败，请换一张或先转成 JPG") from error


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

    # iPhone 照片（HEIC / HEIF）统一转成 JPEG 再落盘：浏览器与 Flutter 都渲染不了
    # HEIC，存下来会变成「传上去了但哪儿都看不见」。
    if is_heif(content):
        content = heif_to_jpeg(content, max_bytes=max_bytes)
        extension = "jpg"
        logger.info("HEIC 已转 JPEG 落盘（%d 字节）", len(content))

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


__all__ = [
    "HEIF_EXTENSIONS",
    "heif_to_jpeg",
    "is_heif",
    "looks_like_image",
    "remove_upload",
    "save_image",
]
