"""倒数日管理接口（仅管理员可访问）。

注意：`/stats` 必须定义在 `/{countdown_id}` 之前，否则会被路径参数抢先匹配。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import PageParams, get_countdown_service, get_current_admin
from app.models.countdown import CountdownCycle
from app.schemas.common import MessageResponse, PageResult
from app.schemas.countdown import (
    CountdownCreate,
    CountdownOut,
    CountdownStatsOut,
    CountdownStatusUpdate,
    CountdownUpdate,
)
from app.services.countdown_service import CountdownService

router = APIRouter(
    prefix="/countdowns",
    tags=["后台-代办事项-倒数日"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/stats", response_model=CountdownStatsOut, summary="倒数日概览统计")
def countdown_stats(
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownStatsOut:
    return service.stats()


@router.get("", response_model=PageResult[CountdownOut], summary="倒数日列表（分页 + 搜索）")
def list_countdowns(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="事项 / 备注模糊搜索"),
    member_id: Optional[int] = Query(None, description="按归属用户（会员）筛选"),
    cycle: Optional[CountdownCycle] = Query(None, description="按重复周期筛选"),
    is_active: Optional[bool] = Query(None, description="是否有效筛选"),
    service: CountdownService = Depends(get_countdown_service),
) -> PageResult[CountdownOut]:
    items, total = service.list_countdowns(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        member_id=member_id,
        cycle=cycle.value if cycle else None,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@router.post(
    "",
    response_model=CountdownOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建倒数日",
)
def create_countdown(
    payload: CountdownCreate,
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    return service.create_countdown(payload)


@router.get("/{countdown_id}", response_model=CountdownOut, summary="倒数日详情")
def get_countdown(
    countdown_id: int,
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    return service.get_countdown(countdown_id)


@router.put("/{countdown_id}", response_model=CountdownOut, summary="更新倒数日")
def update_countdown(
    countdown_id: int,
    payload: CountdownUpdate,
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    return service.update_countdown(countdown_id, payload)


@router.patch("/{countdown_id}/status", response_model=CountdownOut, summary="启用 / 停用倒数日")
def update_countdown_status(
    countdown_id: int,
    payload: CountdownStatusUpdate,
    service: CountdownService = Depends(get_countdown_service),
) -> CountdownOut:
    return service.set_status(countdown_id, payload.is_active)


@router.delete("/{countdown_id}", response_model=MessageResponse, summary="删除倒数日")
def delete_countdown(
    countdown_id: int,
    service: CountdownService = Depends(get_countdown_service),
) -> MessageResponse:
    service.delete_countdown(countdown_id)
    return MessageResponse(message="删除成功")
