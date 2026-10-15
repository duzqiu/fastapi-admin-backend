"""用户中心（会员）个人中心接口：资料查看/修改、头像与背景图上传、修改密码（邮箱验证码）。

前缀 `/member`，需要会员令牌（scope=member）。

图片**只保留上传**：读取不再单独开接口，`GET /member/profile` 的出参里带
`avatar_url` / `background_url`（都是按会员 ID 解析出来的可用地址；头像没上传时是
系统默认头像，背景图没上传时是空串）。
"""

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.api.deps import get_client_ip, get_current_member, get_member_auth_service, get_member_service
from app.models.member import Member
from app.schemas.common import MessageResponse
from app.schemas.email import SendCodeResponse
from app.schemas.member import (
    MediaUploadOut,
    MemberChangePassword,
    MemberOut,
    MemberProfileUpdate,
)
from app.services.member_auth_service import MemberAuthService
from app.services.member_service import MemberService

router = APIRouter(prefix="/member", tags=["前端-用户中心-个人中心"])


@router.get("/profile", response_model=MemberOut, summary="查看我的资料")
def get_profile(current_member: Member = Depends(get_current_member)) -> Member:
    """返回资料全字段，其中两个**可直接用于 `<img src>` 的图片地址**：

    - `avatar_url`：按会员 ID 解析出来的那张头像（`avatars/{会员ID}/` 目录），
      还没上传过时等于系统默认头像地址 `DEFAULT_AVATAR`；
    - `background_url`：按会员 ID 解析出来的背景图（`backgrounds/{会员ID}/` 目录），
      **没上传过时是空串**（前端按「不铺背景图」处理）。
    """
    return current_member


@router.put("/profile", response_model=MemberOut, summary="修改我的资料")
def update_profile(
    payload: MemberProfileUpdate,
    current_member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> Member:
    """可修改：昵称、头像地址、背景图地址、性别、生日、手机号、个人简介、地区。

    字段均为可选，**未传的字段保持原值**；生日不能晚于今天。
    改完再调 `GET /member/profile` 即可回读（出参含 `avatar_url` / `background_url`）。
    """
    return service.update_profile(current_member, payload)


@router.post("/profile/avatar", response_model=MediaUploadOut, summary="上传头像")
def upload_avatar(
    file: UploadFile = File(..., description="头像图片，支持 jpg/jpeg/png/webp/gif，最大 5MB"),
    current_member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> MediaUploadOut:
    """上传成功后会返回可访问的 URL，并自动更新会员头像字段。

    落盘位置：`{UPLOAD_DIR}/avatars/{会员ID}/avatar_{会员ID}_{随机串}.{ext}`
    —— 一个会员一个目录，覆盖上传时旧文件会被清掉（目录里只留当前这一张）。
    """
    result = service.save_avatar(current_member, file)
    return MediaUploadOut(**result)


@router.post("/profile/background", response_model=MediaUploadOut, summary="上传背景图")
def upload_background(
    file: UploadFile = File(..., description="背景图，支持 jpg/jpeg/png/webp/gif，最大 5MB"),
    current_member: Member = Depends(get_current_member),
    service: MemberService = Depends(get_member_service),
) -> MediaUploadOut:
    """上传成功后会返回可访问的 URL，并自动更新会员背景图字段（与头像同一套规则）。

    落盘位置：`{UPLOAD_DIR}/backgrounds/{会员ID}/background_{会员ID}_{随机串}.{ext}`
    —— 一个会员一个目录，覆盖上传时旧文件会被清掉。
    读回来用 `GET /member/profile` 的 `background_url`（没上传时是空串）。
    """
    result = service.save_background(current_member, file)
    return MediaUploadOut(**result)


@router.post("/send-code", response_model=SendCodeResponse, summary="发送邮箱验证码（已登录）")
def send_code(
    request: Request,
    current_member: Member = Depends(get_current_member),
    service: MemberAuthService = Depends(get_member_auth_service),
) -> SendCodeResponse:
    """向**当前登录账号**的邮箱发送「修改密码」验证码，无需传邮箱，防止给他人邮箱发码。

    未配置 SMTP（`MAIL_ENABLED=false`）时不会真实发信，验证码会写入服务端日志；
    开启 `EMAIL_CODE_DEBUG_RETURN` 且 DEBUG=true 时会在响应 `debug_code` 中回显，便于本地联调。
    """
    data = service.send_code_to_member(current_member, get_client_ip(request))
    return SendCodeResponse(**data)


@router.post("/profile/change-password", response_model=MessageResponse, summary="修改我的密码")
def change_password(
    payload: MemberChangePassword,
    current_member: Member = Depends(get_current_member),
    service: MemberAuthService = Depends(get_member_auth_service),
) -> MessageResponse:
    """流程：先调 `POST /member/send-code` 拿邮箱验证码，再提交「验证码 + 新密码 + 确认密码」。

    入参 `confirm_password` 需与 `new_password` 一致；验证码一次性使用。
    """
    service.change_password(current_member, payload.code, payload.new_password)
    return MessageResponse(message="密码修改成功，请使用新密码重新登录")
