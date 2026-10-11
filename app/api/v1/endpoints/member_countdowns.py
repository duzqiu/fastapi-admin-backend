"""用户中心（会员）倒数日接口：管理自己的倒数日。

前缀 `/member/countdowns`，需要会员令牌（scope=member）。
所有接口都按当前登录会员隔离，只能读写自己的数据；越权访问返回 403。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import PageParams, get_countdown_service, get_current_member
from app.models.countdown import CountdownCycle
from app.models.member import Member
from app.schemas.common import MessageResponse, PageResult
from app.schemas.countdown import (
    CountdownOut,
    CountdownSelfCreate,
    CountdownSelfUpdate,
    CountdownUpdate,
)
from app.services.countdown_service import CountdownService

router = APIRouter(prefix="/member/countdowns", tags=["前端-代办事项-倒数日"])


@router.get("", response_model=PageResult[CountdownOut], summary="我的倒数日列表")
def list_my_countdowns(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="事项 / 备注模糊搜索"),
    cycle: Optional[CountdownCycle] = Query(None, description="按重复周期筛选"),
    is_active: Optional[bool] = Query(None, description="是否有效筛选"),
    current_member: Member = Depends(get_current_member),
    service: CountdownService = Depends(get_countdown_service),
) -> PageResult[CountdownOut]:
    items, total = service.list_countdowns(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        member_id=current_member.id,
        cycle=cycle.value if cycle else None,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@router.post(
    "",
    response_model=CountdownOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增我的倒数日",
)
def create_my_countdown(
    payload: CountdownSelfCreate,
    current_member: Member = Depends(get_current_member),
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    """归属用户自动取当前登录会员，无需也不能在入参里传 member_id。"""
    return service.create_for_member(current_member, payload)


@router.get("/{countdown_id}", response_model=CountdownOut, summary="我的倒数日详情")
def get_my_countdown(
    countdown_id: int,
    current_member: Member = Depends(get_current_member),
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    item = service.get_own_or_404(countdown_id, current_member)
    return service.get_countdown(item.id)


@router.put("/{countdown_id}", response_model=CountdownOut, summary="修改我的倒数日")
def update_my_countdown(
    countdown_id: int,
    payload: CountdownSelfUpdate,
    current_member: Member = Depends(get_current_member),
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    """字段全部可选；归属用户不可修改，是否生效用 is_active 传入。"""
    service.get_own_or_404(countdown_id, current_member)
    return service.update_countdown(
        countdown_id, CountdownUpdate(**payload.model_dump(exclude_unset=True))
    )


@router.delete("/{countdown_id}", response_model=MessageResponse, summary="删除我的倒数日")
def delete_my_countdown(
    countdown_id: int,
    current_member: Member = Depends(get_current_member),
    service: CountdownService = Depends(get_countdown_service),
) -> MessageResponse:
    service.get_own_or_404(countdown_id, current_member)
    service.delete_countdown(countdown_id)
    return MessageResponse(message="删除成功")
