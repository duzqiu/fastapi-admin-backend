"""数据库初始化：建表 + 补列 + 写入初始数据。

在应用启动（lifespan）时调用，幂等，可重复执行。

`create_all()` **只建表、不改表**，所以这里分三步走：
1. `create_tables()` 建出缺失的表；
2. `drop_legacy_tables()` 删除已下线功能（菜品管理 / 待办）遗留的表
   （见 app/db/legacy_cleanup.py，可用 `DROP_LEGACY_TABLES=false` 关闭）；
3. `sync_missing_columns()` 把模型里新增、库里还没有的**列**补上
   （见 app/db/schema_sync.py）—— 于是「拉代码 → 重建镜像 → 起服务」即可，
   不需要任何人手工执行迁移命令。

只加列能覆盖绝大多数「加字段」的迭代；字符串列**放宽长度**也会自动处理
（`sync_column_types`，只放宽不放窄）；改类型 / 删列 / 加约束这类变更仍要走
Alembic（`python -m alembic upgrade head`，见 README 第十一节）。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import hash_password
from app.core.site_password import hash_site_password
from app.core.utils import generate_member_no, utcnow
from app.db.base import Base
from app.db.legacy_cleanup import drop_legacy_tables
from app.db.schema_sync import sync_column_types, sync_missing_columns
from app.db.session import SessionLocal, engine
from app.models import (  # noqa: F401  确保模型已注册
    EmailCode,
    Member,
    SiteSetting,
    User,
)
from app.models.member import MemberGender
from app.models.site_setting import (
    DEFAULT_ABOUT_PASSWORD,
    DEFAULT_WELCOME_BLESSING,
    DEFAULT_WELCOME_SUBTITLE,
    DEFAULT_WELCOME_TITLE,
)
from app.models.user import UserRole

# 用户中心演示会员（密码统一 members123，昵称/性别/生日为一个完整资料示例）
DEFAULT_MEMBERS = [
    {
        "email": "alice@example.com",
        "nickname": "Alice",
        "gender": MemberGender.FEMALE.value,
        "birthday": date(1996, 5, 20),
        "phone": "13800000001",
        "bio": "喜欢读书和徒步，正在学习 FastAPI。",
        "region": "上海",
        "is_active": True,
    },
    {
        "email": "bob@example.com",
        "nickname": "Bob",
        "gender": MemberGender.MALE.value,
        "birthday": date(1992, 11, 3),
        "phone": "13800000002",
        "bio": "后端工程师，关注分层架构与数据库设计。",
        "region": "北京",
        "is_active": True,
    },
    {
        "email": "carol@example.com",
        "nickname": "Carol",
        "gender": MemberGender.UNKNOWN.value,
        "birthday": None,
        "phone": "",
        "bio": "刚注册，还没来得及完善资料。",
        "region": "",
        "is_active": False,
    },
]
DEFAULT_MEMBER_PASSWORD = "members123"


def create_tables() -> None:
    """根据 ORM 模型创建所有表（已存在的表不会重复创建）。"""
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表已就绪: %s", ", ".join(Base.metadata.tables.keys()))


def create_initial_site_setting(db: Session) -> None:
    """写入站点设置单例（只在还没有时创建）。"""
    if db.get(SiteSetting, 1) is not None:
        return
    db.add(
        SiteSetting(
            id=1,
            welcome_title=DEFAULT_WELCOME_TITLE,
            welcome_subtitle=DEFAULT_WELCOME_SUBTITLE,
            welcome_blessing=DEFAULT_WELCOME_BLESSING,
            about_password_enabled=True,
            about_password_hash=hash_site_password(DEFAULT_ABOUT_PASSWORD),
            about_password_text=DEFAULT_ABOUT_PASSWORD,
        )
    )
    db.commit()
    logger.info(
        "已写入个人网站默认设置（关于我默认密码：%s）", DEFAULT_ABOUT_PASSWORD
    )


def create_initial_superuser(db: Session) -> None:
    """创建初始管理员账号（不存在时才创建）。"""
    exists = db.execute(
        select(User).where(User.username == settings.FIRST_SUPERUSER_USERNAME)
    ).scalars().first()
    if exists:
        logger.info("初始管理员已存在，跳过创建: %s", settings.FIRST_SUPERUSER_USERNAME)
        return

    admin = User(
        username=settings.FIRST_SUPERUSER_USERNAME,
        email=settings.FIRST_SUPERUSER_EMAIL,
        nickname=settings.FIRST_SUPERUSER_NICKNAME,
        hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    logger.info(
        "已创建初始管理员: %s / %s",
        settings.FIRST_SUPERUSER_USERNAME,
        settings.FIRST_SUPERUSER_PASSWORD,
    )


def _unique_member_no(taken: set) -> str:
    """为演示会员生成互不重复的随机编号（与注册流程生成规则一致）。"""
    while True:
        candidate = generate_member_no()
        if candidate not in taken:
            taken.add(candidate)
            return candidate


def create_initial_members(db: Session) -> None:
    """写入演示会员（表为空时才写入）。"""
    if db.execute(select(Member)).scalars().first():
        return
    taken_no: set = set()
    for item in DEFAULT_MEMBERS:
        db.add(
            Member(
                member_no=_unique_member_no(taken_no),
                email=item["email"],
                nickname=item["nickname"],
                gender=item["gender"],
                birthday=item["birthday"],
                phone=item["phone"],
                bio=item["bio"],
                region=item["region"],
                is_active=item["is_active"],
                email_verified=True,
                email_verified_at=utcnow(),
                hashed_password=hash_password(DEFAULT_MEMBER_PASSWORD),
            )
        )
    db.commit()
    logger.info(
        "已写入 %d 条演示会员数据（密码统一为 %s）", len(DEFAULT_MEMBERS), DEFAULT_MEMBER_PASSWORD
    )


def _is_outdated_schema(error: SQLAlchemyError) -> bool:
    """判断是不是「库里缺 ORM 里新加的列」——忘了跑迁移的典型症状。

    三个方言的措辞不同，都认一下：PostgreSQL `column xxx does not exist`、
    SQLite `no such column: xxx`、MySQL `Unknown column 'xxx'`。
    """
    text = str(getattr(error, "orig", error)).lower()
    return (
        "does not exist" in text
        or "no such column" in text
        or "unknown column" in text
    )


def init_db() -> None:
    """完整初始化流程。"""
    try:
        create_tables()
        # 下线功能清库：删除菜品管理 / 待办遗留的表（白名单，删前请备份）。
        drop_legacy_tables(engine)
        # 老库兜底：模型里新增、库里还没有的列，在这里补上（只加列）。
        # 有它，「拉代码 → 重建镜像 → 起服务」就够了，不必手工跑迁移。
        sync_missing_columns(engine)
        # 老库兜底：字符串列长度不够时自动放宽（例如会员编号 6 -> 10 位）。
        # 只放宽不放窄，老用户的 6 位编号原样保留。
        sync_column_types(engine)
        db = SessionLocal()
        try:
            create_initial_superuser(db)
            create_initial_members(db)
            create_initial_site_setting(db)
        finally:
            db.close()
    except SQLAlchemyError as error:
        if _is_outdated_schema(error):
            logger.error(
                "数据库结构比代码旧（%s）。自动补列没能解决，多半是「变更不止于加列」"
                "（改类型 / 删列 / 加约束）或当前库账号没有 DDL 权限，请用 Alembic 迁移：\n"
                "    python -m alembic upgrade head\n"
                "老库第一次接入 Alembic（库里还没有 alembic_version 表）的做法见 README 第十一节。",
                error,
            )
        raise


if __name__ == "__main__":
    init_db()
