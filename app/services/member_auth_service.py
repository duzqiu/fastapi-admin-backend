"""会员认证服务：验证码、注册、登录、刷新令牌、重置密码。

注意：会员令牌带 `scope=member`，与后台账号令牌（`scope=staff`）互不通用。
"""

import secrets
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessError, ConflictError, UnauthorizedError
from app.core.security import (
    TOKEN_SCOPE_MEMBER,
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.utils import generate_member_no, utcnow
from app.models.email_code import EmailScene
from app.models.member import Member, MemberGender
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberRegister, MemberResetPassword
from app.services.email_code_service import EmailCodeService


class MemberAuthService:
    """用户中心认证业务逻辑。"""

    # 会员编号查重重试次数（900000 的编号空间下几乎用不到第二次）
    MEMBER_NO_MAX_ATTEMPTS = 10

    def __init__(self, db: Session) -> None:
        self.db = db
        self.members = MemberRepository(db)
        self.codes = EmailCodeService(db)

    # ------------------------- 工具 -------------------------
    @staticmethod
    def _issue_tokens(member: Member) -> Dict[str, Any]:
        extra = {"email": member.email}
        return {
            "access_token": create_access_token(
                member.id, extra=extra, scope=TOKEN_SCOPE_MEMBER
            ),
            "refresh_token": create_refresh_token(member.id, scope=TOKEN_SCOPE_MEMBER),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    @staticmethod
    def _default_nickname(email: str) -> str:
        """注册未填昵称时，用邮箱前缀 + 随机数字生成一个不重复的昵称。"""
        prefix = email.split("@")[0][:12] or "user"
        return f"{prefix}_{secrets.randbelow(9000) + 1000}"

    def _generate_member_no(self) -> str:
        """生成一个未被占用的 10 位随机会员编号（老用户的 6 位编号保持原样）。

        90 亿的编号空间下顺序重试基本不会发生第二次；数据库层面还有唯一索引兜底，
        即使极端并发下撞号，也不会写入重复编号。
        """
        for _ in range(self.MEMBER_NO_MAX_ATTEMPTS):
            candidate = generate_member_no()
            if not self.members.member_no_taken(candidate):
                return candidate
        raise BusinessError("会员编号生成失败，请稍后重试")

    def _get_active_member(self, email: str) -> Member:
        member = self.members.get_by_email(email.lower())
        if member is None:
            raise UnauthorizedError("邮箱或密码错误")
        if not member.is_active:
            raise UnauthorizedError("账号已被禁用，请联系客服")
        return member

    # ------------------------- 验证码 -------------------------
    def send_code(
        self, email: str, scene: EmailScene, request_ip: str = ""
    ) -> Dict[str, Any]:
        """按场景做业务校验后再发送验证码。"""
        email = email.lower()
        registered = self.members.email_taken(email)

        if scene == EmailScene.REGISTER and registered:
            raise ConflictError("该邮箱已注册，请直接登录或使用「忘记密码」找回")
        if scene == EmailScene.RESET_PASSWORD and not registered:
            raise BusinessError("该邮箱尚未注册")
        if scene == EmailScene.CHANGE_EMAIL and registered:
            raise ConflictError("该邮箱已被其他账号使用")
        if scene == EmailScene.CHANGE_PASSWORD:
            # 改密码场景必须绑定登录态，邮箱只能取当前账号，避免给任意邮箱发码
            raise BusinessError("修改密码请在登录状态下调用 /member/send-code 获取验证码")

        return self.codes.send_code(email, scene.value, request_ip)

    def send_code_to_member(self, member: Member, request_ip: str = "") -> Dict[str, Any]:
        """已登录状态发送「修改密码」验证码：邮箱固定为当前账号邮箱，无需前端传。"""
        return self.codes.send_code(
            member.email.lower(), EmailScene.CHANGE_PASSWORD.value, request_ip
        )

    # ------------------------- 注册 / 登录 -------------------------
    def register(self, payload: MemberRegister, request_ip: str = "") -> Member:
        """邮箱验证码注册。

        注册成功时会随机生成一个 10 位、全局不重复的会员编号（`member_no`）。
        """
        email = str(payload.email).lower()

        if self.members.email_taken(email):
            raise ConflictError("该邮箱已注册，请直接登录")

        # 校验验证码（失败会消耗尝试次数；校验通过后标记已使用）
        self.codes.verify(email, EmailScene.REGISTER.value, payload.code)

        member = self.members.create(
            member_no=self._generate_member_no(),
            email=email,
            hashed_password=hash_password(payload.password),
            nickname=self._default_nickname(email),
            avatar=settings.DEFAULT_AVATAR,
            gender=MemberGender.UNKNOWN.value,
            is_active=True,
            email_verified=True,
            email_verified_at=utcnow(),
            register_ip=request_ip or "",
        )
        self.db.commit()
        self.db.refresh(member)
        return member

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """邮箱 + 密码登录，返回令牌。"""
        member = self._get_active_member(email)
        if not verify_password(password, member.hashed_password):
            # 不区分「邮箱不存在」与「密码错误」，避免账号枚举
            raise UnauthorizedError("邮箱或密码错误")

        member.last_login_at = utcnow()
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return self._issue_tokens(member)

    def refresh(self, refresh_token: str) -> Dict[str, Any]:
        """用会员 refresh_token 换取新的令牌对。"""
        payload = decode_token(
            refresh_token,
            expected_type=TOKEN_TYPE_REFRESH,
            expected_scope=TOKEN_SCOPE_MEMBER,
        )
        member = self.members.get(int(payload["sub"]))
        if member is None:
            raise UnauthorizedError("用户不存在")
        if not member.is_active:
            raise UnauthorizedError("账号已被禁用，请联系客服")
        return self._issue_tokens(member)

    # ------------------------- 密码 -------------------------
    def reset_password(self, payload: MemberResetPassword) -> None:
        """忘记密码：邮箱验证码 + 新密码。"""
        email = str(payload.email).lower()
        member = self.members.get_by_email(email)
        if member is None:
            raise BusinessError("该邮箱尚未注册")

        self.codes.verify(email, EmailScene.RESET_PASSWORD.value, payload.code)

        member.hashed_password = hash_password(payload.new_password)
        self.db.add(member)
        self.db.commit()

    def change_password(self, member: Member, code: str, new_password: str) -> None:
        """登录状态下自助修改密码：邮箱验证码 + 新密码。"""
        # 校验验证码（失败会消耗尝试次数；校验通过后标记已使用）
        self.codes.verify(member.email.lower(), EmailScene.CHANGE_PASSWORD.value, code)

        if verify_password(new_password, member.hashed_password):
            raise BusinessError("新密码不能与当前密码相同")

        member.hashed_password = hash_password(new_password)
        self.db.add(member)
        self.db.commit()

    def get_member_by_id(self, member_id: int) -> Optional[Member]:
        return self.members.get(member_id)
