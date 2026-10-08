"""后台订单管理接口（仅管理员）。

覆盖：订单列表与筛选、订单详情、状态流转（接单 / 完成 / 取消）、删除、经营统计。
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import PageParams, get_current_admin, get_dish_order_service
from app.models.dish_order import DishOrder, OrderStatus
from app.schemas.common import MessageResponse, PageResult
from app.schemas.dish_order import OrderListItem, OrderOut, OrderStatsOut, OrderStatusUpdate
from app.services.dish_order_service import DishOrderService

router = APIRouter(
    prefix="/dish-orders",
    tags=["订单管理"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("", response_model=PageResult[OrderListItem], summary="订单列表")
def list_orders(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="订单号 / 桌号模糊搜索"),
    status_filter: Optional[OrderStatus] = Query(None, alias="status", description="状态筛选"),
    created_after: Optional[datetime] = Query(None, description="下单时间起（含）"),
    created_before: Optional[datetime] = Query(None, description="下单时间止（含）"),
    service: DishOrderService = Depends(get_dish_order_service),
) -> PageResult[OrderListItem]:
    items, total = service.admin_list(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        status=status_filter.value if status_filter else None,
        created_after=created_after,
        created_before=created_before,
    )
    return PageResult.create(
        [OrderListItem.model_validate(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.get("/stats", response_model=OrderStatsOut, summary="订单统计")
def order_stats(service: DishOrderService = Depends(get_dish_order_service)) -> OrderStatsOut:
    return OrderStatsOut(**service.stats())


@router.get("/dish-sales", summary="菜品销量排行（按订单明细聚合）")
def dish_sales(
    limit: int = Query(10, ge=1, le=100),
    service: DishOrderService = Depends(get_dish_order_service),
) -> List[dict]:
    return service.dish_sales(limit)


@router.get("/{order_id}", response_model=OrderOut, summary="订单详情")
def get_order(
    order_id: int, service: DishOrderService = Depends(get_dish_order_service)
) -> DishOrder:
    return service.get_order_or_404(order_id)


@router.patch("/{order_id}/status", response_model=OrderOut, summary="修改订单状态")
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    service: DishOrderService = Depends(get_dish_order_service),
) -> DishOrder:
    """状态流转：待接单 → 已接单 → 已完成；待接单 / 已接单可取消。

    取消订单会自动回滚菜品与套餐的库存、扣减对应销量。
    """
    return service.admin_update_status(order_id, payload.status.value)


@router.delete("/{order_id}", response_model=MessageResponse, summary="删除订单")
def delete_order(
    order_id: int, service: DishOrderService = Depends(get_dish_order_service)
) -> MessageResponse:
    service.admin_delete(order_id)
    return MessageResponse(message="删除成功")
