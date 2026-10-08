"""会员资料服务。

同时服务两个场景（共用同一份数据模型与仓储）：
1. C 端：会员在用户中心查看/修改自己的资料、上传头像；
2. B 端：管理员在后台查看会员列表、修改资料、启用禁用、重置密码、删除。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
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
        """会员自助修改资料（头像地址也可直接传 URL）。"""
        data = payload.model_dump(exclude_unset=True)
        if "gender" in data and data["gender"] is not None:
            gender = data["gender"]
            data["gender"] = gender.value if isinstance(gender, MemberGender) else gender

        self.members.update(member, **data)
        self.db.commit()
        self.db.refresh(member)
        return member

    def save_avatar(self, member: Member, upload: UploadFile) -> Dict[str, Any]:
        """保存上传的头像文件并更新会员头像地址。"""
        result = save_image(upload, subdir="avatars", prefix="avatar", identifier=member.id)
        # 删除上一张由本地上传的头像，避免磁盘堆积
        remove_upload(member.avatar)
        self.members.update(member, avatar=result["url"])
        self.db.commit()
        self.db.refresh(member)
        return result

    # ------------------------- B 端：后台管理 -------------------------
    def admin_update(self, member_id: int, payload: MemberAdminUpdate) -> Member:
        """管理员修改会员资料 / 启用状态。"""
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
        self.members.delete(member)
        self.db.commit()
