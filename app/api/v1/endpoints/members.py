"""后台会员管理接口（仅管理员可访问）。

用于在后台查看用户中心注册用户的信息、修改资料、启用/禁用、重置密码与删除。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import PageParams, get_current_admin, get_member_service
from app.core.member_media import DEFAULT_AVATAR_FILE, media_file_response
from app.models.member import Member, MemberGender
from app.schemas.common import MessageResponse, PageResult
from app.schemas.member import (
    MediaUploadOut,
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
    """可修改昵称、头像地址、背景图地址、性别、生日、手机号、简介、地区与启用状态。"""
    return service.admin_update(member_id, payload)


@router.post("/{member_id}/avatar", response_model=MediaUploadOut, summary="上传会员头像")
def upload_member_avatar(
    member_id: int,
    file: UploadFile = File(..., description="头像图片，支持 jpg/jpeg/png/webp/gif，最大 5MB"),
    service: MemberService = Depends(get_member_service),
) -> MediaUploadOut:
    """管理员代会员上传头像，落盘规则与会员自助上传完全一致。

    存放位置：`{UPLOAD_DIR}/avatars/{会员ID}/avatar_{会员ID}_{随机串}.{ext}`
    —— 以会员 ID 为维度建目录，覆盖上传时该目录里的旧文件会被清掉，只留当前这一张。
    """
    member = service.get_or_404(member_id)
    return MediaUploadOut(**service.save_avatar(member, file))


@router.get("/{member_id}/avatar", summary="读取会员头像（按会员 ID）")
def get_member_avatar(
    member_id: int,
    service: MemberService = Depends(get_member_service),
) -> FileResponse:
    """按会员 ID 读取头像图片，可直连 `<img src>`；未上传过时返回系统默认头像。

    与出参里的 `avatar_url` 指向同一份文件，区别只是这里直接返回图片流。
    """
    return media_file_response(
        service.avatar_file(service.get_or_404(member_id)), fallback=DEFAULT_AVATAR_FILE
    )


@router.post(
    "/{member_id}/background", response_model=MediaUploadOut, summary="上传会员背景图"
)
def upload_member_background(
    member_id: int,
    file: UploadFile = File(..., description="背景图，支持 jpg/jpeg/png/webp/gif，最大 5MB"),
    service: MemberService = Depends(get_member_service),
) -> MediaUploadOut:
    """管理员代会员上传背景图，落盘规则与头像完全一致（只是目录换成 `backgrounds`）。

    存放位置：`{UPLOAD_DIR}/backgrounds/{会员ID}/background_{会员ID}_{随机串}.{ext}`
    """
    member = service.get_or_404(member_id)
    return MediaUploadOut(**service.save_background(member, file))


@router.get("/{member_id}/background", summary="读取会员背景图（按会员 ID）")
def get_member_background(
    member_id: int,
    service: MemberService = Depends(get_member_service),
) -> FileResponse:
    """按会员 ID 读取背景图；**背景没有默认图**，没上传过返回 404。"""
    return media_file_response(service.background_file(service.get_or_404(member_id)))


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
