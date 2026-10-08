"""邮件发送模块。

设计要点：
- 关闭 `MAIL_ENABLED` 时不会真正发信，验证码只打印到日志，方便本地开发；
- 只做「发信」这一件事，验证码的生成、校验、限流由服务层负责；
- 使用标准库 smtplib，无需额外依赖（FastAPI 的同步路由在线程池中执行，不会阻塞事件循环）。
"""

import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.logging import logger

# 验证码场景 -> 邮件标题与说明文案
SCENE_TEXTS = {
    "register": ("注册账号", "注册账号"),
    "reset_password": ("重置密码", "重置登录密码"),
    "change_email": ("更换邮箱", "更换绑定邮箱"),
}


def build_code_mail(code: str, scene: str) -> tuple[str, str]:
    """返回 (邮件标题, HTML 正文)。"""
    scene_title, scene_desc = SCENE_TEXTS.get(scene, ("身份验证", "身份验证"))
    subject = f"[{settings.PROJECT_NAME}] {scene_title}验证码"
    minutes = settings.EMAIL_CODE_EXPIRE_MINUTES
    html = f"""
    <div style="max-width:520px;margin:0 auto;padding:28px;font-family:-apple-system,
                'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2937;">
      <h2 style="margin:0 0 8px;font-size:19px;">{settings.PROJECT_NAME}</h2>
      <p style="margin:0 0 22px;color:#6b7280;font-size:13px;">
        你正在进行「{scene_desc}」操作，请在 {minutes} 分钟内完成验证。
      </p>
      <div style="padding:18px 0;text-align:center;background:#f5f7fb;border-radius:10px;">
        <span style="font-size:30px;font-weight:700;letter-spacing:8px;color:#4f46e5;">{code}</span>
      </div>
      <p style="margin:22px 0 0;color:#9ca3af;font-size:12px;line-height:1.7;">
        验证码 {minutes} 分钟内有效，每个验证码只能使用一次。<br />
        如果这不是你的操作，请忽略本邮件，你的账号仍然安全。
      </p>
    </div>
    """
    return subject, html


def send_mail(to: str, subject: str, html: str) -> bool:
    """发送 HTML 邮件，返回是否真正投递成功。"""
    if not settings.mail_configured:
        logger.warning(
            "[mail][dev] 未启用 SMTP，邮件未真实发送 -> to=%s, subject=%s", to, subject
        )
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = settings.MAIL_FROM
    message["To"] = to
    message.attach(MIMEText(html, "html", "utf-8"))

    try:
        if settings.MAIL_USE_SSL:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.MAIL_HOST, settings.MAIL_PORT, timeout=settings.MAIL_TIMEOUT
            )
        else:
            server = smtplib.SMTP(
                settings.MAIL_HOST, settings.MAIL_PORT, timeout=settings.MAIL_TIMEOUT
            )
            server.starttls()
        with server:
            server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.sendmail(settings.MAIL_USERNAME, [to], message.as_string())
        logger.info("[mail] 邮件已发送 -> %s", to)
        return True
    except Exception as exc:  # pragma: no cover - 依赖外部 SMTP 服务
        logger.error("[mail] 邮件发送失败 -> %s：%s", to, exc)
        return False


def send_email_code(to: str, code: str, scene: str) -> bool:
    """发送验证码邮件。"""
    subject, html = build_code_mail(code, scene)
    return send_mail(to, subject, html)


def debug_code_enabled() -> bool:
    """是否允许把验证码回显在接口响应中（仅本地联调）。"""
    return bool(settings.EMAIL_CODE_DEBUG_RETURN and settings.DEBUG)
