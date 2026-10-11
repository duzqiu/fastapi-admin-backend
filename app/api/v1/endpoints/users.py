"""用户管理接口（仅管理员可访问）。"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import PageParams, get_current_admin, get_user_service
from app.models.user import User, UserRole
from app.schemas.common import MessageResponse, PageResult
from app.schemas.user import (
    UserCreate,
    UserOut,
    UserPasswordReset,
    UserStatusUpdate,
    UserUpdate,
)
from app.services.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["后台-后台账号-账号管理"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("", response_model=PageResult[UserOut], summary="用户列表（分页 + 搜索）")
def list_users(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="用户名/邮箱/昵称模糊搜索"),
    role: Optional[UserRole] = Query(None, description="角色筛选"),
    is_active: Optional[bool] = Query(None, description="启用状态筛选"),
    service: UserService = Depends(get_user_service),
) -> PageResult[UserOut]:
    items, total = service.list_users(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        role=role.value if role else None,
        is_active=is_active,
    )
    return PageResult.create(
        [UserOut.model_validate(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建用户",
)
def create_user(payload: UserCreate, service: UserService = Depends(get_user_service)) -> User:
    return service.create_user(payload)


@router.get("/{user_id}", response_model=UserOut, summary="用户详情")
def get_user(user_id: int, service: UserService = Depends(get_user_service)) -> User:
    return service.get_or_404(user_id)


@router.put("/{user_id}", response_model=UserOut, summary="更新用户")
def update_user(
    user_id: int, payload: UserUpdate, service: UserService = Depends(get_user_service)
) -> User:
    return service.update_user(user_id, payload)


@router.patch("/{user_id}/status", response_model=UserOut, summary="启用 / 禁用用户")
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    current_user: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
) -> User:
    return service.set_status(user_id, payload.is_active, current_user)


@router.patch("/{user_id}/password", response_model=MessageResponse, summary="重置用户密码")
def reset_user_password(
    user_id: int,
    payload: UserPasswordReset,
    service: UserService = Depends(get_user_service),
) -> MessageResponse:
    service.reset_password(user_id, payload.new_password)
    return MessageResponse(message="密码重置成功")


@router.delete("/{user_id}", response_model=MessageResponse, summary="删除用户")
def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    service: UserService = Depends(get_user_service),
) -> MessageResponse:
    service.delete_user(user_id, current_user)
    return MessageResponse(message="删除成功")
