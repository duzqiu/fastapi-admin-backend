"""邮箱验证码服务：生成、限流、发送、校验。

职责边界：只处理「验证码生命周期」，不判断业务规则
（比如「注册场景邮箱必须未注册」这类规则由会员认证服务负责）。
"""

import secrets
from datetime import timedelta
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.logging import logger
from app.core.mailer import debug_code_enabled, send_email_code
from app.core.utils import utcnow
from app.models.email_code import EmailCode
from app.repositories.email_code_repository import EmailCodeRepository


class EmailCodeService:
    """验证码业务逻辑。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.codes = EmailCodeRepository(db)

    # ------------------------- 生成与发送 -------------------------
    @staticmethod
    def _generate_code() -> str:
        length = settings.EMAIL_CODE_LENGTH
        return f"{secrets.randbelow(10 ** length):0{length}d}"

    def send_code(self, email: str, scene: str, request_ip: str = "") -> Dict[str, Any]:
        """发送验证码，返回发送结果（含调试用明文验证码）。"""
        email = email.lower()

        # 1. 冷却时间校验，防止刷接口
        latest = self.codes.latest(email, scene)
        if latest is not None:
            elapsed = (utcnow() - latest.created_at).total_seconds()
            if elapsed < settings.EMAIL_CODE_RESEND_SECONDS:
                wait = int(settings.EMAIL_CODE_RESEND_SECONDS - elapsed) + 1
                raise BusinessError(f"发送过于频繁，请 {wait} 秒后再试")

        # 2. 生成并落库
        code = self._generate_code()
        self.codes.create(
            email=email,
            code=code,
            scene=scene,
            expires_at=utcnow() + timedelta(minutes=settings.EMAIL_CODE_EXPIRE_MINUTES),
            request_ip=request_ip or "",
        )
        self.db.commit()

        # 3. 发送邮件（未启用 SMTP 时只写日志，不影响流程）
        sent = send_email_code(email, code, scene)
        if not sent:
            logger.warning(
                "[用户中心] 未真实发送邮件，验证码 -> email=%s scene=%s code=%s", email, scene, code
            )

        return {
            "email": email,
            "scene": scene,
            "sent": sent,
            "expires_in": settings.EMAIL_CODE_EXPIRE_MINUTES * 60,
            "resend_after": settings.EMAIL_CODE_RESEND_SECONDS,
            "debug_code": code if debug_code_enabled() else None,
        }

    # ------------------------- 校验 -------------------------
    def verify(
        self, email: str, scene: str, code: str, *, consume: bool = True
    ) -> EmailCode:
        """校验验证码；默认成功后标记已使用，consume=False 时仅校验。

        消耗成功验证码的事务由调用方提交；失败尝试及超限作废仍立即持久化。
        """
        email = email.lower()
        record = self.codes.latest_usable(email, scene)
        if record is None:
            raise BusinessError("验证码不存在或已过期，请重新获取")

        if record.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            self.codes.invalidate(email, scene)
            self.db.commit()
            raise BusinessError("验证码错误次数过多，请重新获取")

        if record.code != (code or "").strip():
            record.attempts += 1
            self.db.add(record)
            self.db.commit()
            remaining = settings.EMAIL_CODE_MAX_ATTEMPTS - record.attempts
            raise BusinessError(f"验证码不正确，还可尝试 {max(remaining, 0)} 次")

        if consume:
            record.used_at = utcnow()
            self.db.add(record)
            self.db.flush()
        return record
