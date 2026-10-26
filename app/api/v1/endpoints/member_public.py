"""会员公开资料接口（帖子作者主页用，**无需登录**）。

和后台会员管理（`members.py`，挂管理员依赖）完全分开：

- 路径独立：`GET /members/{member_id}/public`，与后台的 `/members/{member_id}` 不重叠；
- 不挂鉴权：任何人点开帖子作者头像都能看，不依赖登录态；
- 出参独立：用 `MemberPublicOut`，只含昵称 / 头像 / 简介 / 地区 / 会员编号，
  邮箱、手机号、生日等隐私字段不返回；
- 被禁用的账号按「不存在」处理，避免对外暴露账号状态。

作者发布的帖子走已有的 `GET /posts/by-member/{member_id}`（无需登录、只出已通过）。
"""

from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import (
    PageParams,
    get_current_member,
    get_member_service,
    get_optional_member,
)
from app.core.exceptions import NotFoundError
from app.models.member import Member
from app.schemas.common import MessageResponse, PageResult
from app.schemas.member import MemberPublicOut
from app.services.member_service import MemberService

router = APIRouter(prefix="/members", tags=["前端-会员公开资料"])


@router.get(
    "/me/following",
    response_model=PageResult[MemberPublicOut],
    summary="我关注的人（需登录）",
)
def list_my_following(
    page_params: PageParams = Depends(),
    member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> PageResult[MemberPublicOut]:
    """「我的 ▸ 关注」列表：当前会员关注的人，最近关注的在前。"""
    items, total = service.list_following(
        member.id,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    for item in items:
        item.is_following = True
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@router.post(
    "/{member_id}/follow",
    response_model=MessageResponse,
    summary="关注会员（需登录）",
)
def follow_member(
    member_id: int,
    member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> MessageResponse:
    """关注某个会员；重复关注是幂等的，不能关注自己。"""
    service.follow(member, member_id)
    return MessageResponse(message="已关注")


@router.delete(
    "/{member_id}/follow",
    response_model=MessageResponse,
    summary="取消关注（需登录）",
)
def unfollow_member(
    member_id: int,
    member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> MessageResponse:
    """取消关注；本来没关注也返回成功。"""
    service.unfollow(member, member_id)
    return MessageResponse(message="已取消关注")


@router.get(
    "/{member_id}/public",
    response_model=MemberPublicOut,
    summary="查看会员公开资料（作者主页用，无需登录）",
)
def get_public_member(
    member_id: int,
    viewer: Optional[Member] = Depends(get_optional_member),
    service: MemberService = Depends(get_member_service),
) -> Member:
    """返回帖子作者主页要展示的公开资料。

    只出昵称、性别、头像、简介、地区与会员编号；不存在的会员和已禁用的账号都回 404。
    带上会员令牌时，`is_following` 表示当前登录会员是否已关注 TA。
    """
    member = service.get_or_404(member_id)
    if not member.is_active:
        raise NotFoundError(f"会员不存在: id={member_id}")
    member.is_following = service.is_following(
        viewer.id if viewer is not None else None, member_id
    )
    return member
