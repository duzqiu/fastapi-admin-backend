"""后台会员管理接口（仅管理员可访问）。

用于在后台查看用户中心注册用户的信息、修改资料、启用/禁用、重置密码与删除。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import PageParams, get_current_admin, get_member_service
from app.models.member import Member, MemberGender
from app.schemas.common import MessageResponse, PageResult
from app.schemas.member import (
    MemberAdminUpdate,
    MemberListItem,
    MemberOut,
    MemberPasswordReset,
    MemberStatsOut,
    MemberStatusUpdate,
)
from app.services.member_service import MemberService

router = APIRouter(
    prefix="/members",
    tags=["后台-用户管理-用户列表"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("", response_model=PageResult[MemberListItem], summary="会员列表（分页 + 搜索）")
def list_members(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="邮箱 / 昵称 / 手机号模糊搜索"),
    gender: Optional[MemberGender] = Query(None, description="性别筛选"),
    is_active: Optional[bool] = Query(None, description="启用状态筛选"),
    email_verified: Optional[bool] = Query(None, description="邮箱是否已验证"),
    registered_after: Optional[datetime] = Query(None, description="注册时间起（含）"),
    registered_before: Optional[datetime] = Query(None, description="注册时间止（含）"),
    service: MemberService = Depends(get_member_service),
) -> PageResult[MemberListItem]:
    items, total = service.list_members(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        gender=gender.value if gender else None,
        is_active=is_active,
        email_verified=email_verified,
        registered_after=registered_after,
        registered_before=registered_before,
    )
    return PageResult.create(
        [MemberListItem.model_validate(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.get("/stats", response_model=MemberStatsOut, summary="会员统计概览")
def member_stats(service: MemberService = Depends(get_member_service)) -> MemberStatsOut:
    return MemberStatsOut(**service.stats())


@router.get("/{member_id}", response_model=MemberOut, summary="会员详情")
def get_member(member_id: int, service: MemberService = Depends(get_member_service)) -> Member:
    return service.get_or_404(member_id)


@router.put("/{member_id}", response_model=MemberOut, summary="修改会员资料")
def update_member(
    member_id: int,
    payload: MemberAdminUpdate,
    service: MemberService = Depends(get_member_service),
) -> Member:
    """可修改昵称、头像地址、性别、生日、手机号、简介与启用状态。"""
    return service.admin_update(member_id, payload)


@router.patch("/{member_id}/status", response_model=MemberOut, summary="启用 / 禁用会员")
def update_member_status(
    member_id: int,
    payload: MemberStatusUpdate,
    service: MemberService = Depends(get_member_service),
) -> Member:
    """禁用后该会员无法登录，且已签发的令牌会立即失效（每次请求都会校验状态）。"""
    return service.admin_set_status(member_id, payload.is_active)


@router.patch("/{member_id}/password", response_model=MessageResponse, summary="重置会员密码")
def reset_member_password(
    member_id: int,
    payload: MemberPasswordReset,
    service: MemberService = Depends(get_member_service),
) -> MessageResponse:
    service.admin_reset_password(member_id, payload.new_password)
    return MessageResponse(message="密码重置成功")


@router.delete(
    "/{member_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="删除会员",
)
def delete_member(
    member_id: int,
    service: MemberService = Depends(get_member_service),
) -> MessageResponse:
    service.admin_delete(member_id)
    return MessageResponse(message="删除成功")
