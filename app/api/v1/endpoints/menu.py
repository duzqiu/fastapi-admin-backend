"""点菜菜单接口（C 端）。

- 菜单浏览（分类 / 标签 / 菜品）**无需登录**，方便扫码即可查看；
- 下单允许匿名（扫码点菜），若带会员令牌则关联到该会员；
- 「我的订单」必须登录会员。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    PageParams,
    get_current_member,
    get_dish_order_service,
    get_dish_service,
    get_optional_member,
)
from app.models.dish import Dish
from app.models.dish_order import OrderStatus
from app.models.member import Member
from app.schemas.common import PageResult
from app.schemas.dish import DishSpecOut, DishTagOut, MenuCategoryOut, MenuDishItem
from app.schemas.dish_order import OrderCreate, OrderListItem, OrderOut
from app.services.dish_order_service import DishOrderService
from app.services.dish_service import DishService

router = APIRouter(prefix="/menu", tags=["前端-点菜菜单-菜品与订单"])


def _to_menu_item(dish: Dish) -> MenuDishItem:
    """组装点菜菜单条目：只暴露可售的套餐与已启用的标签。"""
    item = MenuDishItem.model_validate(dish)
    item.specs = [DishSpecOut.model_validate(spec) for spec in dish.specs if spec.is_active]
    item.tags = [DishTagOut.model_validate(tag) for tag in dish.tags if tag.is_active]
    return item


@router.get("/categories", response_model=List[MenuCategoryOut], summary="菜单分类")
def menu_categories(service: DishService = Depends(get_dish_service)) -> List[MenuCategoryOut]:
    """只返回启用且含在售菜品的分类，附带可点菜品数量。"""
    return [MenuCategoryOut.model_validate(item) for item in service.menu_categories()]


@router.get("/tags", response_model=List[DishTagOut], summary="菜单标签")
def menu_tags(service: DishService = Depends(get_dish_service)) -> List[DishTagOut]:
    """只返回启用的标签（与菜单分类一致，停用的标签不对顾客展示）。"""
    items = service.list_tags(only_active=True)
    return [DishTagOut.model_validate(item) for item in items]


@router.get("/dishes", response_model=PageResult[MenuDishItem], summary="菜单菜品列表")
def menu_dishes(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="菜名 / 描述模糊搜索"),
    category_id: Optional[int] = Query(None, description="分类筛选"),
    tag_id: Optional[int] = Query(None, description="标签筛选"),
    is_recommended: Optional[bool] = Query(None, description="只看推荐"),
    include_unavailable: bool = Query(False, description="是否包含已售罄 / 下架菜品"),
    service: DishService = Depends(get_dish_service),
) -> PageResult[MenuDishItem]:
    """默认只返回「在售且有库存」的菜品，附带套餐与售卖规则。"""
    items, total = service.menu_dishes(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        category_id=category_id,
        tag_id=tag_id,
        is_recommended=is_recommended,
        include_unavailable=include_unavailable,
    )
    return PageResult.create(
        [_to_menu_item(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.get("/dishes/{dish_id}", response_model=MenuDishItem, summary="菜品详情（点菜用）")
def menu_dish_detail(
    dish_id: int, service: DishService = Depends(get_dish_service)
) -> MenuDishItem:
    """返回菜品详情与全部可售套餐（含价格、库存、销量与售卖规则）。"""
    return _to_menu_item(service.get_menu_dish(dish_id))


@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="提交订单（点菜）",
)
def submit_order(
    payload: OrderCreate,
    member: Optional[Member] = Depends(get_optional_member),
    service: DishOrderService = Depends(get_dish_order_service),
) -> OrderOut:
    """下单成功后立即扣减库存并累加销量，可在后台「订单管理」中查看与操作。

    - 菜品有套餐时必须传 `spec_id`；没有套餐时不要传；
    - 会校验起购数量、每单限购、每日限量、供应时段与库存。
    """
    order = service.submit_order(payload, member)
    return OrderOut.model_validate(order)


@router.get("/orders", response_model=PageResult[OrderListItem], summary="我的订单")
def my_orders(
    page_params: PageParams = Depends(),
    status_filter: Optional[OrderStatus] = Query(None, alias="status", description="状态筛选"),
    member: Member = Depends(get_current_member),
    service: DishOrderService = Depends(get_dish_order_service),
) -> PageResult[OrderListItem]:
    items, total = service.list_my_orders(
        member_id=member.id,
        page=page_params.page,
        page_size=page_params.page_size,
        status=status_filter.value if status_filter else None,
    )
    return PageResult.create(
        [OrderListItem.model_validate(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.get("/orders/{order_id}", response_model=OrderOut, summary="订单详情")
def my_order_detail(
    order_id: int,
    member: Member = Depends(get_current_member),
    service: DishOrderService = Depends(get_dish_order_service),
) -> OrderOut:
    order = service.get_order_or_404(order_id)
    if order.member_id != member.id:
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError("无权查看该订单")
    return OrderOut.model_validate(order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, summary="取消订单")
def cancel_order(
    order_id: int,
    member: Member = Depends(get_current_member),
    service: DishOrderService = Depends(get_dish_order_service),
) -> OrderOut:
    """仅「待接单 / 已接单」的订单可取消，取消后库存与销量会自动回滚。"""
    return OrderOut.model_validate(service.cancel_order(order_id, member_id=member.id))
