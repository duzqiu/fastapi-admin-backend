"""会员资料服务。

同时服务两个场景（共用同一份数据模型与仓储）：
1. C 端：会员在用户中心查看/修改自己的资料、上传头像；
2. B 端：管理员在后台查看会员列表、修改资料、启用禁用、重置密码、删除。
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.member_media import (
    AVATAR_SUBDIR,
    BACKGROUND_SUBDIR,
    find_media_file,
    media_dir,
    resolve_avatar_url,
    resolve_background_url,
)
from app.core.exceptions import NotFoundError
from app.core.logging import logger
from app.core.security import hash_password
from app.core.storage import remove_upload, save_image
from app.models.member import Member, MemberGender
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberAdminUpdate, MemberProfileUpdate


class MemberService:
    """会员资料与后台管理业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.members = MemberRepository(db)

    # ------------------------- 查询 -------------------------
    def get_or_404(self, member_id: int) -> Member:
        member = self.members.get(member_id)
        if member is None:
            raise NotFoundError(f"会员不存在: id={member_id}")
        return member

    def list_members(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        gender: Optional[str] = None,
        is_active: Optional[bool] = None,
        email_verified: Optional[bool] = None,
        registered_after: Optional[datetime] = None,
        registered_before: Optional[datetime] = None,
    ) -> Tuple[List[Member], int]:
        return self.members.search(
            keyword=keyword,
            gender=gender,
            is_active=is_active,
            email_verified=email_verified,
            registered_after=registered_after,
            registered_before=registered_before,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def stats(self) -> Dict[str, Any]:
        """会员统计（用于后台首页与会员管理页顶部指标）。"""
        total = self.members.count()
        active = self.members.count_active()
        return {
            "total": total,
            "active": active,
            "disabled": total - active,
            "verified": self.members.count_verified(),
            "new_in_7_days": self.members.count_registered_within_days(7),
            "gender_distribution": self.members.count_by_gender(),
        }

    def recent_members(self, limit: int = 5) -> List[Member]:
        return self.members.recent(limit=limit)

    # ------------------------- C 端：资料维护 -------------------------
    def update_profile(self, member: Member, payload: MemberProfileUpdate) -> Member:
        """会员自助修改资料：昵称 / 头像地址 / 性别 / 生日 / 手机号 / 简介 / 地区。

        只更新**显式传进来**的字段（`exclude_unset`），没传的保持原值。
        """
        data = payload.model_dump(exclude_unset=True)
        if "gender" in data and data["gender"] is not None:
            gender = data["gender"]
            data["gender"] = gender.value if isinstance(gender, MemberGender) else gender

        self.members.update(member, **data)
        self.db.commit()
        self.db.refresh(member)
        return member

    def avatar_dir(self, member_id: int) -> Path:
        """该会员自己的头像目录：`{UPLOAD_DIR}/avatars/{会员ID}`（可能还不存在）。"""
        return media_dir(AVATAR_SUBDIR, member_id)

    def background_dir(self, member_id: int) -> Path:
        """该会员自己的背景图目录：`{UPLOAD_DIR}/backgrounds/{会员ID}`。"""
        return media_dir(BACKGROUND_SUBDIR, member_id)

    def avatar_file(self, member: Member) -> Optional[Path]:
        """会员头像在磁盘上的文件路径；**没上传过返回 None**（应回退系统默认头像）。"""
        return find_media_file(AVATAR_SUBDIR, member.id, member.avatar)

    def background_file(self, member: Member) -> Optional[Path]:
        """会员背景图在磁盘上的文件路径；**没上传过返回 None**（背景没有默认图）。"""
        return find_media_file(BACKGROUND_SUBDIR, member.id, member.background)

    def avatar_url(self, member: Member) -> str:
        """可直接访问的头像地址；没上传过时是系统默认头像地址。"""
        return resolve_avatar_url(member.id, member.avatar)

    def background_url(self, member: Member) -> str:
        """可直接访问的背景图地址；**没上传过时是空串**。"""
        return resolve_background_url(member.id, member.background)

    def _clear_media_dir(self, subdir: str, member_id: int, keep: str = "") -> None:
        """清空该会员某个图片目录里除 `keep` 之外的文件（目录本身保留）。"""
        directory = media_dir(subdir, member_id)
        if not directory.is_dir():
            return
        for item in directory.iterdir():
            if not item.is_file() or item.name == keep:
                continue
            try:
                item.unlink()
            except OSError as exc:  # pragma: no cover - 磁盘异常
                logger.warning("删除图片文件失败: %s (%s)", item, exc)

    def _clear_avatar_dir(self, member_id: int, keep: str = "") -> None:
        """清空该会员头像目录里除 `keep` 之外的文件。"""
        self._clear_media_dir(AVATAR_SUBDIR, member_id, keep)

    def _clear_background_dir(self, member_id: int, keep: str = "") -> None:
        """清空该会员背景图目录里除 `keep` 之外的文件。"""
        self._clear_media_dir(BACKGROUND_SUBDIR, member_id, keep)

    def _save_media(
        self,
        member: Member,
        upload: UploadFile,
        *,
        subdir: str,
        prefix: str,
        field: str,
    ) -> Dict[str, Any]:
        """保存上传的图片（头像 / 背景图共用），并写回对应字段。

        存放规则：`{UPLOAD_DIR}/{subdir}/{会员ID}/{prefix}_{会员ID}_{随机串}.{ext}`
        —— 一个会员一个目录，读取时也按会员 ID 找。
        """
        # 先写新文件：目录不存在时 save_image 会一并建出来
        result = save_image(
            upload,
            subdir=f"{subdir}/{member.id}",
            prefix=prefix,
            identifier=member.id,
        )
        # 清掉上一张：库里那个地址先按 URL 删，目录里的其它残留（比如上一版平铺的
        # 旧文件）再扫一遍 —— 保证一个会员目录下只留当前这一张。
        remove_upload(getattr(member, field))
        self._clear_media_dir(subdir, member.id, keep=result["filename"])
        self.members.update(member, **{field: result["url"]})
        self.db.commit()
        self.db.refresh(member)
        return result

    def save_avatar(self, member: Member, upload: UploadFile) -> Dict[str, Any]:
        """保存上传的头像文件并更新会员头像地址。

        存放规则：`{UPLOAD_DIR}/avatars/{会员ID}/avatar_{会员ID}_{随机串}.{ext}`
        —— 一个会员一个目录，读取时也按会员 ID 找（见 `avatar_file`）。
        """
        return self._save_media(
            member, upload, subdir=AVATAR_SUBDIR, prefix="avatar", field="avatar"
        )

    def save_background(self, member: Member, upload: UploadFile) -> Dict[str, Any]:
        """保存上传的背景图并更新会员背景图地址。

        与头像同一套规则：`{UPLOAD_DIR}/backgrounds/{会员ID}/background_{会员ID}_{随机串}.{ext}`
        —— 一个会员一个目录，读取时也按会员 ID 找（见 `background_file`）。
        """
        return self._save_media(
            member,
            upload,
            subdir=BACKGROUND_SUBDIR,
            prefix="background",
            field="background",
        )

    # ------------------------- B 端：后台管理 -------------------------
    def admin_update(self, member_id: int, payload: MemberAdminUpdate) -> Member:
        """管理员修改会员资料 / 启用状态。

        可改字段与会员自助一致（昵称 / 头像 / 性别 / 生日 / 手机号 / 简介 / 地区），
        另外支持 `is_active`；同样只更新显式传进来的字段。
        """
        member = self.get_or_404(member_id)
        data = payload.model_dump(exclude_unset=True)
        if "gender" in data and data["gender"] is not None:
            gender = data["gender"]
            data["gender"] = gender.value if isinstance(gender, MemberGender) else gender

        self.members.update(member, **data)
        self.db.commit()
        self.db.refresh(member)
        return member

    def admin_set_status(self, member_id: int, is_active: bool) -> Member:
        member = self.get_or_404(member_id)
        self.members.update(member, is_active=is_active)
        self.db.commit()
        self.db.refresh(member)
        return member

    def admin_reset_password(self, member_id: int, new_password: str) -> None:
        member = self.get_or_404(member_id)
        self.members.update(member, hashed_password=hash_password(new_password))
        self.db.commit()

    def admin_delete(self, member_id: int) -> None:
        member = self.get_or_404(member_id)
        remove_upload(member.avatar)
        remove_upload(member.background)
        # 该会员自己的图片目录一起清掉（目录里只会有它自己的图）
        self._clear_avatar_dir(member.id)
        self._clear_background_dir(member.id)
        self.members.delete(member)
        self.db.commit()
