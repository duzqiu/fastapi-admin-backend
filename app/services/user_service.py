"""用户服务：用户增删改查与状态管理。"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    """用户业务逻辑层。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    # ------------------------- 查询 -------------------------
    def get_or_404(self, user_id: int) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFoundError(f"用户不存在: id={user_id}")
        return user

    def list_users(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[list[User], int]:
        return self.users.search(
            keyword=keyword,
            role=role,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    # ------------------------- 写入 -------------------------
    def create_user(self, payload: UserCreate) -> User:
        if self.users.username_taken(payload.username):
            raise ConflictError(f"用户名已存在: {payload.username}")
        if self.users.email_taken(payload.email):
            raise ConflictError(f"邮箱已被占用: {payload.email}")

        user = self.users.create(
            username=payload.username,
            email=payload.email,
            nickname=payload.nickname or payload.username,
            role=payload.role.value if isinstance(payload.role, UserRole) else payload.role,
            is_active=payload.is_active,
            hashed_password=hash_password(payload.password),
        )
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(self, user_id: int, payload: UserUpdate) -> User:
        user = self.get_or_404(user_id)

        if payload.email and payload.email != user.email:
            if self.users.email_taken(str(payload.email), exclude_id=user_id):
                raise ConflictError(f"邮箱已被占用: {payload.email}")

        data = payload.model_dump(exclude_unset=True)
        if "role" in data and data["role"] is not None:
            data["role"] = (
                data["role"].value if isinstance(data["role"], UserRole) else data["role"]
            )

        # 不允许把最后一个管理员降级
        if data.get("role") and data["role"] != UserRole.ADMIN.value and user.is_admin:
            self._ensure_not_last_admin(user_id, "不能修改最后一个管理员的角色")

        self.users.update(user, **data)
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_status(self, user_id: int, is_active: bool, operator: User) -> User:
        user = self.get_or_404(user_id)
        if user.id == operator.id and not is_active:
            raise ForbiddenError("不能禁用当前登录账号")
        if not is_active and user.is_admin:
            self._ensure_not_last_admin(user_id, "不能禁用最后一个管理员")

        self.users.update(user, is_active=is_active)
        self.db.commit()
        self.db.refresh(user)
        return user

    def reset_password(self, user_id: int, new_password: str) -> None:
        user = self.get_or_404(user_id)
        self.users.update(user, hashed_password=hash_password(new_password))
        self.db.commit()

    def delete_user(self, user_id: int, operator: User) -> None:
        user = self.get_or_404(user_id)
        if user.id == operator.id:
            raise ForbiddenError("不能删除当前登录账号")
        if user.is_admin:
            self._ensure_not_last_admin(user_id, "不能删除最后一个管理员")

        self.users.delete(user)
        self.db.commit()

    # ------------------------- 内部校验 -------------------------
    def _ensure_not_last_admin(self, user_id: int, message: str) -> None:
        admin_total = self.users.count_by_role(UserRole.ADMIN.value)
        if admin_total <= 1:
            raise BusinessError(message)
