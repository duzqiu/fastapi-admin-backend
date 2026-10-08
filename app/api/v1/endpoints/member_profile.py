"""用户中心（会员）个人中心接口：资料查看/修改、头像上传、修改密码。

前缀 `/member`，需要会员令牌（scope=member）。
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_current_member, get_member_auth_service, get_member_service
from app.models.member import Member
from app.schemas.common import MessageResponse
from app.schemas.member import (
    AvatarUploadOut,
    MemberChangePassword,
    MemberOut,
    MemberProfileUpdate,
)
from app.services.member_auth_service import MemberAuthService
from app.services.member_service import MemberService

router = APIRouter(prefix="/member", tags=["用户中心-个人中心"])


@router.get("/profile", response_model=MemberOut, summary="查看我的资料")
def get_profile(current_member: Member = Depends(get_current_member)) -> Member:
    return current_member


@router.put("/profile", response_model=MemberOut, summary="修改我的资料")
def update_profile(
    payload: MemberProfileUpdate,
    current_member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> Member:
    """支持修改：昵称、头像地址、性别、生日、手机号、个人简介。

    字段均为可选，未传的字段保持原值；生日不能晚于今天。
    """
    return service.update_profile(current_member, payload)


@router.post("/profile/avatar", response_model=AvatarUploadOut, summary="上传头像")
def upload_avatar(
    file: UploadFile = File(..., description="头像图片，支持 jpg/jpeg/png/webp/gif，最大 2MB"),
    current_member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> AvatarUploadOut:
    """上传成功后会返回可访问的 URL，并自动更新会员头像字段。"""
    result = service.save_avatar(current_member, file)
    return AvatarUploadOut(**result)


@router.post("/profile/change-password", response_model=MessageResponse, summary="修改我的密码")
def change_password(
    payload: MemberChangePassword,
    current_member: Member = Depends(get_current_member),
    service: MemberAuthService = Depends(get_member_auth_service),
) -> MessageResponse:
    service.change_password(current_member, payload.old_password, payload.new_password)
    return MessageResponse(message="密码修改成功")
