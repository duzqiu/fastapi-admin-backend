"""全局配置模块。

所有可调参数集中在此，通过环境变量或 `.env` 文件覆盖，
业务代码只依赖 `settings` 对象，不直接读取 `os.environ`。
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/core/config.py -> app/core -> app -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """项目配置项（高内聚：所有配置只在这里定义一次）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 基础信息 ----------
    # 系统显示名称：会出现在接口文档标题、根路径响应、后台「系统信息」卡片与邮件标题中
    PROJECT_NAME: str = "后台管理系统"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "基于 FastAPI + SQLAlchemy 2.0 的分层后台接口系统"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # ---------- 数据库 ----------
    # 本地默认使用 SQLite；迁移到 PostgreSQL / MySQL 时只需修改此变量
    # PostgreSQL: postgresql+psycopg://user:password@127.0.0.1:5432/dbname
    # MySQL:      mysql+pymysql://user:password@127.0.0.1:3306/dbname?charset=utf8mb4
    DATABASE_URL: str = "sqlite:///./data/app.db"
    SQL_ECHO: bool = False

    # ---------- 安全 / JWT ----------
    SECRET_KEY: str = "please-change-this-secret-key-in-production-0123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # ---------- 跨域 ----------
    # 多个来源用英文逗号分隔，例如 "http://a.com,http://b.com"
    BACKEND_CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    # ---------- 初始超级管理员（首次建表时自动创建） ----------
    FIRST_SUPERUSER_USERNAME: str = "admin"
    FIRST_SUPERUSER_PASSWORD: str = "admin123"
    FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
    FIRST_SUPERUSER_NICKNAME: str = "超级管理员"

    # ---------- 分页 ----------
    DEFAULT_PAGE_SIZE: int = 10
    MAX_PAGE_SIZE: int = 200

    # ---------- 用户中心（会员）：邮件发送 ----------
    # MAIL_ENABLED=false 时不真正发信，验证码只写入日志（本地开发用）
    MAIL_ENABLED: bool = False
    MAIL_HOST: str = "smtp.example.com"
    MAIL_PORT: int = 465
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = "后台管理系统 <noreply@example.com>"
    MAIL_USE_SSL: bool = True
    MAIL_TIMEOUT: int = 10

    # ---------- 用户中心（会员）：邮箱验证码 ----------
    EMAIL_CODE_LENGTH: int = 6
    EMAIL_CODE_EXPIRE_MINUTES: int = 10
    EMAIL_CODE_RESEND_SECONDS: int = 60
    EMAIL_CODE_MAX_ATTEMPTS: int = 5
    # 非生产环境把验证码回显在接口响应里，方便前端联调（生产务必置 false）
    EMAIL_CODE_DEBUG_RETURN: bool = True

    # ---------- 用户中心（会员）：默认头像 ----------
    # 注册成功但尚未上传头像时写入该地址，由 app/static 下的内置资源托管
    DEFAULT_AVATAR: str = "/api/v1/assets/default-avatar.svg"

    # ---------- 图片上传（会员头像 / 菜品图片） ----------
    # 相对路径以「项目根目录」为基准
    UPLOAD_DIR: str = "./data/uploads"
    IMAGE_MAX_SIZE_MB: int = 5
    IMAGE_ALLOWED_EXTENSIONS: str = "jpg,jpeg,png,webp,gif"

    @property
    def cors_origins(self) -> List[str]:
        """把逗号分隔的字符串解析为列表。"""
        return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def image_extensions(self) -> List[str]:
        """允许上传的图片后缀（小写、不含点）。"""
        return [
            item.strip().lower().lstrip(".")
            for item in self.IMAGE_ALLOWED_EXTENSIONS.split(",")
            if item.strip()
        ]

    @property
    def upload_dir(self) -> Path:
        """上传目录的绝对路径（相对路径以项目根目录为基准）。"""
        raw = Path(self.UPLOAD_DIR).expanduser()
        if not raw.is_absolute():
            raw = PROJECT_ROOT / raw
        return raw.resolve()

    @property
    def upload_url_prefix(self) -> str:
        """上传文件的对外访问前缀。

        挂在 API 前缀下（/api/v1/static），这样前端的 /api 代理与 Nginx 的
        /api 反向代理可以原样复用，不需要额外配置静态资源规则。
        """
        return f"{self.API_V1_PREFIX}/static"

    @property
    def mail_configured(self) -> bool:
        return bool(self.MAIL_ENABLED and self.MAIL_HOST and self.MAIL_USERNAME)


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置工厂，保证全局只解析一次环境变量。"""
    return Settings()


settings: Settings = get_settings()
