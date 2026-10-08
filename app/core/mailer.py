"""邮件发送模块。

设计要点：
- 关闭 `MAIL_ENABLED` 时不会真正发信，验证码只打印到日志，方便本地开发；
- 只做「发信」这一件事，验证码的生成、校验、限流由服务层负责；
- 使用标准库 smtplib，无需额外依赖（FastAPI 的同步路由在线程池中执行，不会阻塞事件循环）。
"""

import base64
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr

from app.core.config import settings
from app.core.logging import logger

# 验证码场景 -> 邮件标题与说明文案
SCENE_TEXTS = {
    "register": ("注册账号", "注册账号"),
    "reset_password": ("重置密码", "重置登录密码"),
    "change_email": ("更换邮箱", "更换绑定邮箱"),
    "change_password": ("修改密码", "修改登录密码"),
}


def _brand() -> str:
    """邮件品牌名：取 `MAIL_FROM` 的显示名，未设置时回退到 `PROJECT_NAME`。

    发件人名、邮件标题与正文抬头共用这一个来源，改 `.env` 的 `MAIL_FROM` 即可整体生效。
    """
    name, _ = parseaddr(settings.MAIL_FROM)
    return name or settings.PROJECT_NAME


def build_code_mail(code: str, scene: str) -> tuple[str, str]:
    """返回 (邮件标题, HTML 正文)。"""
    scene_title, scene_desc = SCENE_TEXTS.get(scene, ("身份验证", "身份验证"))
    brand = _brand()
    minutes = settings.EMAIL_CODE_EXPIRE_MINUTES
    subject = f"【{brand}】{scene_title}验证码"

    # 全部使用内联样式：多数邮件客户端会剥离 <style>，且不支持 flex / 外部字体
    html = f"""
    <div style="background:#f3f4f6;padding:32px 16px;font-family:-apple-system,
                BlinkMacSystemFont,'PingFang SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;">
      <div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:16px;
                  overflow:hidden;border:1px solid #e5e7eb;">
        <div style="background:#4f46e5;padding:22px 32px;text-align:center;">
          <div style="font-size:21px;font-weight:700;color:#ffffff;letter-spacing:2px;">{brand}</div>
          <div style="margin-top:6px;font-size:12px;color:#ddd6fe;letter-spacing:1px;">
            {scene_title}验证
          </div>
        </div>
        <div style="padding:30px 32px 26px;">
          <p style="margin:0 0 20px;font-size:14px;color:#374151;line-height:1.8;">
            你好，你正在进行「{scene_desc}」操作，请输入下方验证码完成验证。
          </p>
          <div style="margin:0 0 20px;padding:22px 0;text-align:center;background:#f8fafc;
                      border:1px dashed #c7d2fe;border-radius:12px;">
            <span style="font-size:32px;font-weight:700;letter-spacing:10px;color:#4f46e5;
                         font-family:'SF Mono',Menlo,Consolas,monospace;">{code}</span>
          </div>
          <p style="margin:0 0 22px;font-size:13px;color:#6b7280;line-height:1.8;">
            验证码 {minutes} 分钟内有效，且仅可使用一次，请勿转发给他人。
          </p>
          <div style="height:1px;background:#f3f4f6;margin:0 0 18px;"></div>
          <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.8;">
            如果这不是你本人的操作，请忽略本邮件，你的账号仍然安全。<br />
            本邮件由系统自动发送，请勿直接回复。
          </p>
        </div>
      </div>
    </div>
    """
    return subject, html


def _sender_address() -> str:
    """信封发件人地址（SMTP MAIL FROM）。

    优先取 `MAIL_FROM` 中的邮箱部分，缺省时回退到登录账号。
    多数 SMTP 服务（含 QQ 邮箱）要求信封发件人与登录账号一致。
    """
    _, addr = parseaddr(settings.MAIL_FROM)
    return addr or settings.MAIL_USERNAME


def _build_from_header() -> str:
    """构造 `From` 头：只对显示名做 RFC2047 编码，邮箱地址保持明文。

    直接把「显示名 <地址>」整串赋给 `From` 时，Python 会把连地址在内的
    整行编码成 `=?utf-8?b?...?=`，导致部分邮件服务商/客户端解析不到发件地址。
    """
    return formataddr((str(Header(_brand(), "utf-8")), _sender_address()))


def _connect() -> smtplib.SMTP:
    """建立到 SMTP 服务器的连接：MAIL_USE_SSL 走隐式 TLS，否则走 STARTTLS。"""
    if settings.MAIL_USE_SSL:
        return smtplib.SMTP_SSL(
            settings.MAIL_HOST,
            settings.MAIL_PORT,
            timeout=settings.MAIL_TIMEOUT,
            context=ssl.create_default_context(),
        )
    server = smtplib.SMTP(
        settings.MAIL_HOST, settings.MAIL_PORT, timeout=settings.MAIL_TIMEOUT
    )
    server.starttls(context=ssl.create_default_context())
    return server


def _login(server: smtplib.SMTP) -> smtplib.SMTP:
    """登录 SMTP，返回已完成认证的连接。

    `smtplib.login()` 优先使用 AUTH PLAIN，而 QQ / 163 等服务商在凭证错误时
    不会返回 535，而是直接断开连接，导致只能看到「Connection unexpectedly closed」。
    因此在自动认证被断开时改用显式 AUTH LOGIN 重连重试一次，把真实的错误码暴露出来。
    """
    try:
        server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
        return server
    except smtplib.SMTPServerDisconnected:
        logger.warning("[mail] 自动认证被服务端断开，改用 AUTH LOGIN 重试以定位原因")
        try:
            server.close()
        except Exception:  # pragma: no cover - 连接已不可用
            pass

    retry = _connect()
    try:
        retry.ehlo()
        retry.docmd("AUTH", "LOGIN")
        retry.docmd(base64.b64encode(settings.MAIL_USERNAME.encode()).decode())
        code, resp = retry.docmd(
            base64.b64encode(settings.MAIL_PASSWORD.encode()).decode()
        )
        if code != 235:
            raise smtplib.SMTPAuthenticationError(code, resp)
        return retry
    except Exception:
        try:
            retry.close()
        except Exception:  # pragma: no cover
            pass
        raise


def send_mail(to: str, subject: str, html: str) -> bool:
    """发送 HTML 邮件，返回是否真正投递成功。"""
    if not settings.mail_configured:
        logger.warning(
            "[mail][dev] 未启用 SMTP，邮件未真实发送 -> to=%s, subject=%s", to, subject
        )
        return False

    sender = _sender_address()
    message = MIMEMultipart("alternative")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = _build_from_header()
    message["To"] = to
    message.attach(MIMEText(html, "html", "utf-8"))

    server: smtplib.SMTP | None = None
    try:
        server = _login(_connect())
        server.sendmail(sender, [to], message.as_string())
        logger.info("[mail] 邮件已发送 -> %s", to)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "[mail] SMTP 认证失败（code=%s）-> host=%s:%s, user=%s。"
            "请确认 MAIL_PASSWORD 填的是邮箱的「SMTP 授权码」而不是登录密码，"
            "且已在邮箱设置中开启 SMTP/POP3 服务：%s",
            exc.smtp_code,
            settings.MAIL_HOST,
            settings.MAIL_PORT,
            settings.MAIL_USERNAME,
            exc,
        )
        return False
    except Exception as exc:  # pragma: no cover - 依赖外部 SMTP 服务
        logger.error(
            "[mail] 邮件发送失败 -> to=%s, host=%s:%s, user=%s, sender=%s：%s",
            to,
            settings.MAIL_HOST,
            settings.MAIL_PORT,
            settings.MAIL_USERNAME,
            sender,
            exc,
        )
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:  # pragma: no cover - 关闭失败不影响结果
                server.close()


def send_email_code(to: str, code: str, scene: str) -> bool:
    """发送验证码邮件。"""
    subject, html = build_code_mail(code, scene)
    return send_mail(to, subject, html)


def debug_code_enabled() -> bool:
    """是否允许把验证码回显在接口响应中（仅本地联调）。"""
    return bool(settings.EMAIL_CODE_DEBUG_RETURN and settings.DEBUG)
