"""会员公开资料接口（帖子作者主页用，**无需登录**）。

和后台会员管理（`members.py`，挂管理员依赖）完全分开：

- 路径独立：`GET /members/{member_id}/public`，与后台的 `/members/{member_id}` 不重叠；
- 不挂鉴权：任何人点开帖子作者头像都能看，不依赖登录态；
- 出参独立：用 `MemberPublicOut`，只含昵称 / 头像 / 简介 / 地区 / 会员编号，
  邮箱、手机号、生日等隐私字段不返回；
- 被禁用的账号按「不存在」处理，避免对外暴露账号状态。

作者发布的帖子走已有的 `GET /posts/by-member/{member_id}`（无需登录、只出已通过）。
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_member_service
from app.core.exceptions import NotFoundError
from app.models.member import Member
from app.schemas.member import MemberPublicOut
from app.services.member_service import MemberService

router = APIRouter(prefix="/members", tags=["前端-会员公开资料"])


@router.get(
    "/{member_id}/public",
    response_model=MemberPublicOut,
    summary="查看会员公开资料（作者主页用，无需登录）",
)
def get_public_member(
    member_id: int,
    service: MemberService = Depends(get_member_service),
) -> Member:
    """返回帖子作者主页要展示的公开资料。

    只出昵称、头像、简介、地区与会员编号；不存在的会员和已禁用的账号都回 404。
    """
    member = service.get_or_404(member_id)
    if not member.is_active:
        raise NotFoundError(f"会员不存在: id={member_id}")
    return member
