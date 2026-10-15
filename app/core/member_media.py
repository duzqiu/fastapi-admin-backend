"""会员图片（头像 / 背景图）的存放与读取：按会员 ID 建目录，一个会员一个目录。

    {UPLOAD_DIR}/avatars/{会员ID}/avatar_{会员ID}_{随机串}.{ext}
    {UPLOAD_DIR}/backgrounds/{会员ID}/background_{会员ID}_{随机串}.{ext}

所以「存」和「读」都以**会员 ID 为维度**：只要会员 ID 就能定位到那张图，不必知道文件名。

- 头像没上传过时回退**系统默认头像**；
- 背景图没有默认值，没上传就是空（页面按「不铺图」处理）。
"""

import mimetypes
from pathlib import Path
from typing import Optional

from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.exceptions import NotFoundError

# 两种图片的目录名（都在 `{UPLOAD_DIR}/` 之下）。
AVATAR_SUBDIR = "avatars"
BACKGROUND_SUBDIR = "backgrounds"

# 内置静态资源目录（默认头像 default-avatar.svg 就放在这儿，由 /api/v1/assets 托管）
ASSETS_DIR = Path(__file__).resolve().parents[1] / "static"

# 系统默认头像的实体文件：从默认头像的访问地址里取文件名
DEFAULT_AVATAR_FILE = ASSETS_DIR / Path(settings.DEFAULT_AVATAR).name


def media_dir(subdir: str, member_id: int) -> Path:
    """该会员自己的图片目录（`{UPLOAD_DIR}/{subdir}/{会员ID}`，可能还不存在）。"""
    return settings.upload_dir / subdir / str(member_id)


def find_media_file(subdir: str, member_id: int, field_value: str = "") -> Optional[Path]:
    """会员图片在磁盘上的路径；**没上传过返回 None**。

    先按库里存的字段值（`avatar` / `background`）反推磁盘路径（与 `remove_upload`
    同一套解析，外部链接直接跳过）；认不出来再按会员 ID 去它自己的目录里找最后写入
    的那张。两条路都拿不到才是「没有这张图」。
    """
    url = field_value or ""
    if url.startswith(settings.upload_url_prefix):
        relative = url[len(settings.upload_url_prefix):].lstrip("/")
        target = (settings.upload_dir / relative).resolve()
        if settings.upload_dir in target.parents and target.is_file():
            return target

    directory = media_dir(subdir, member_id)
    if directory.is_dir():
        files = [item for item in directory.iterdir() if item.is_file()]
        if files:
            return max(files, key=lambda item: item.stat().st_mtime)
    return None


def resolve_media_url(
    subdir: str,
    member_id: int,
    field_value: str = "",
    default: str = "",
) -> str:
    """可直接访问的图片地址；磁盘上真有就用它，否则回退 `default`。

    资料接口（`GET /member/profile`、`GET /members/{id}`）通过 `avatar_url` /
    `background_url` 把地址一起返回 —— 前端不必再单独调「读取图片」接口。
    """
    path = find_media_file(subdir, member_id, field_value)
    if path is None:
        return default

    try:
        relative = path.resolve().relative_to(settings.upload_dir.resolve()).as_posix()
    except ValueError:  # pragma: no cover - 路径已做穿越校验，理论不会发生
        return default
    return f"{settings.upload_url_prefix}/{relative}"


def media_file_response(path: Optional[Path], fallback: Optional[Path] = None) -> FileResponse:
    """把图片文件作为响应返回；`path` 拿不到就用 `fallback`（还没有就 404）。"""
    target = path if path is not None and path.is_file() else fallback
    if target is None or not target.is_file():
        raise NotFoundError("图片不存在")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(
        target,
        media_type=media_type,
        # 同一个地址会换内容（重新上传），别让客户端缓存住旧图
        headers={"Cache-Control": "no-cache"},
    )


def resolve_avatar_url(member_id: int, field_value: str = "") -> str:
    """头像地址；没上传过时是系统默认头像地址。"""
    return resolve_media_url(
        AVATAR_SUBDIR, member_id, field_value, default=settings.DEFAULT_AVATAR
    )


def resolve_background_url(member_id: int, field_value: str = "") -> str:
    """背景图地址；没上传过时是空串（前端按「不铺图」处理）。"""
    return resolve_media_url(BACKGROUND_SUBDIR, member_id, field_value)


__all__ = [
    "AVATAR_SUBDIR",
    "BACKGROUND_SUBDIR",
    "ASSETS_DIR",
    "DEFAULT_AVATAR_FILE",
    "media_dir",
    "find_media_file",
    "resolve_media_url",
    "resolve_avatar_url",
    "resolve_background_url",
    "media_file_response",
]
