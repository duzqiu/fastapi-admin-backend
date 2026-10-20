"""数据库初始化：建表 + 补列 + 写入初始数据。

在应用启动（lifespan）时调用，幂等，可重复执行。

`create_all()` **只建表、不改表**，所以这里分两步走：
1. `create_tables()` 建出缺失的表；
2. `sync_missing_columns()` 把模型里新增、库里还没有的**列**补上
   （见 app/db/schema_sync.py）—— 于是「拉代码 → 重建镜像 → 起服务」即可，
   不需要任何人手工执行迁移命令。

只加列能覆盖绝大多数「加字段」的迭代；改类型 / 删列 / 加约束这类变更仍要走
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
from app.db.schema_sync import sync_missing_columns
from app.db.session import SessionLocal, engine
from app.models import (  # noqa: F401  确保模型已注册
    Countdown,
    Dish,
    DishCategory,
    DishSpec,
    DishTag,
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
            about_password_hash=hash_site_password(DEFAULT_ABOUT_PASSWORD),
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


# ==================== 点菜菜单演示数据 ====================
DEFAULT_CATEGORIES = [
    {"name": "热菜", "description": "现炒热菜", "sort": 1},
    {"name": "凉菜", "description": "开胃小菜", "sort": 2},
    {"name": "主食", "description": "米饭面点", "sort": 3},
    {"name": "饮品", "description": "冷热饮品", "sort": 4},
]

DEFAULT_TAGS = [
    {"name": "招牌", "color": "danger", "sort": 1},
    {"name": "新品", "color": "success", "sort": 2},
    {"name": "微辣", "color": "warning", "sort": 3},
    {"name": "重辣", "color": "danger", "sort": 4},
    {"name": "素食", "color": "success", "sort": 5},
]

# 菜品 + 套餐（套餐承载价格、库存、销量与售卖规则）
DEFAULT_DISHES = [
    {
        "name": "宫保鸡丁",
        "category": "热菜",
        "description": "选用鸡腿肉与花生米，甜咸微辣，经典川菜。",
        "price": 38,
        "stock": 50,
        "sold_count": 128,
        "unit": "份",
        "is_recommended": True,
        "sort": 1,
        "tags": ["招牌", "微辣"],
        "specs": [
            {"name": "单点", "description": "仅菜品本身", "price": 38, "stock": 50, "sold_count": 90,
             "is_default": True, "sort": 1},
            {"name": "单人套餐", "description": "含米饭一碗 + 例汤", "price": 52, "stock": 30,
             "sold_count": 30, "sort": 2, "min_quantity": 1, "max_quantity_per_order": 5,
             "daily_limit": 20, "serve_start_time": "10:00", "serve_end_time": "22:00"},
            {"name": "双人套餐", "description": "双份菜品 + 米饭两碗 + 例汤两份", "price": 96,
             "stock": 10, "sold_count": 8, "sort": 3, "min_quantity": 1},
        ],
    },
    {
        "name": "麻婆豆腐",
        "category": "热菜",
        "description": "麻、辣、鲜、香，嫩豆腐配牛肉末。",
        "price": 26,
        "stock": 40,
        "sold_count": 96,
        "is_recommended": True,
        "sort": 2,
        "tags": ["重辣", "素食"],
        "specs": [
            {"name": "单点", "price": 26, "stock": 40, "sold_count": 76, "is_default": True, "sort": 1},
            {"name": "下饭套餐", "description": "含米饭一碗", "price": 32, "stock": 20,
             "sold_count": 20, "sort": 2},
        ],
    },
    {
        "name": "凉拌黄瓜",
        "category": "凉菜",
        "description": "清脆爽口，蒜香十足。",
        "price": 16,
        "stock": 30,
        "sold_count": 45,
        "sort": 3,
        "tags": ["素食"],
        "specs": [],  # 演示「没有套餐」的菜品：下单只传 dish_id
    },
    {
        "name": "米饭",
        "category": "主食",
        "description": "东北珍珠米，粒粒分明。",
        "price": 3,
        "stock": 200,
        "sold_count": 320,
        "unit": "碗",
        "sort": 4,
        "tags": [],
        "specs": [],
    },
    {
        "name": "柠檬茶",
        "category": "饮品",
        "description": "现打柠檬，清爽解腻。",
        "price": 12,
        "stock": 60,
        "sold_count": 76,
        "unit": "杯",
        "sort": 5,
        "tags": ["新品"],
        "specs": [
            {"name": "中杯", "price": 12, "stock": 40, "sold_count": 50, "is_default": True, "sort": 1},
            {"name": "大杯", "price": 15, "stock": 20, "sold_count": 26, "sort": 2},
        ],
    },
]


def create_initial_dishes(db: Session) -> None:
    """写入演示分类 / 标签 / 菜品 / 套餐（表为空时才写入）。"""
    if db.execute(select(Dish)).scalars().first():
        return

    category_map = {}
    for item in DEFAULT_CATEGORIES:
        category = DishCategory(**item)
        db.add(category)
        category_map[item["name"]] = category

    tag_map = {}
    for item in DEFAULT_TAGS:
        tag = DishTag(**item)
        db.add(tag)
        tag_map[item["name"]] = tag

    db.flush()

    for item in DEFAULT_DISHES:
        data = {k: v for k, v in item.items() if k not in ("category", "tags", "specs")}
        dish = Dish(category_id=category_map[item["category"]].id, **data)
        dish.tags = [tag_map[name] for name in item["tags"]]
        for spec_data in item["specs"]:
            dish.specs.append(DishSpec(**spec_data))
        db.add(dish)

    db.commit()
    logger.info(
        "已写入演示菜品数据：%d 个分类 / %d 个标签 / %d 道菜",
        len(DEFAULT_CATEGORIES),
        len(DEFAULT_TAGS),
        len(DEFAULT_DISHES),
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
        # 老库兜底：模型里新增、库里还没有的列，在这里补上（只加列）。
        # 有它，「拉代码 → 重建镜像 → 起服务」就够了，不必手工跑迁移。
        sync_missing_columns(engine)
        db = SessionLocal()
        try:
            create_initial_superuser(db)
            create_initial_members(db)
            create_initial_dishes(db)
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
