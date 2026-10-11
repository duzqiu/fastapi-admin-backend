"""后台菜品管理接口（仅管理员）。

包含：菜品 CRUD、上下架、库存调整、图片上传、销量统计，
以及分类（/dish-categories）与标签（/dish-tags）的管理。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import PageParams, get_current_admin, get_dish_service
from app.models.dish import Dish, DishCategory, DishSpec, DishStatus, DishTag
from app.schemas.common import MessageResponse, PageResult, UploadOut
from app.schemas.dish import (
    DishCategoryCreate,
    DishCategoryOut,
    DishCategoryUpdate,
    DishCreate,
    DishListItem,
    DishOut,
    DishSpecCreate,
    DishSpecOut,
    DishSpecUpdate,
    DishStatsOut,
    DishStatusUpdate,
    DishStockUpdate,
    DishTagCreate,
    DishTagOut,
    DishTagUpdate,
    DishUpdate,
)
from app.services.dish_service import DishService

admin_dependency = [Depends(get_current_admin)]

router = APIRouter(prefix="/dishes", tags=["后台-菜品管理-菜品列表"], dependencies=admin_dependency)
category_router = APIRouter(
    prefix="/dish-categories", tags=["后台-菜品管理-菜品分类"], dependencies=admin_dependency
)
tag_router = APIRouter(prefix="/dish-tags", tags=["后台-菜品管理-菜品标签"], dependencies=admin_dependency)


# ==================== 分类 ====================
@category_router.get("", response_model=List[DishCategoryOut], summary="分类列表")
def list_categories(
    only_active: bool = Query(False, description="只返回启用的分类"),
    service: DishService = Depends(get_dish_service),
) -> List[DishCategoryOut]:
    return [
        DishCategoryOut.model_validate(item) for item in service.list_categories(only_active=only_active)
    ]


@category_router.post(
    "", response_model=DishCategoryOut, status_code=status.HTTP_201_CREATED, summary="新建分类"
)
def create_category(
    payload: DishCategoryCreate, service: DishService = Depends(get_dish_service)
) -> DishCategory:
    return service.create_category(payload)


@category_router.put("/{category_id}", response_model=DishCategoryOut, summary="更新分类")
def update_category(
    category_id: int,
    payload: DishCategoryUpdate,
    service: DishService = Depends(get_dish_service),
) -> DishCategory:
    return service.update_category(category_id, payload)


@category_router.delete("/{category_id}", response_model=MessageResponse, summary="删除分类")
def delete_category(
    category_id: int, service: DishService = Depends(get_dish_service)
) -> MessageResponse:
    service.delete_category(category_id)
    return MessageResponse(message="删除成功")


# ==================== 标签 ====================
@tag_router.get("", response_model=List[DishTagOut], summary="标签列表")
def list_tags(
    only_active: bool = Query(False, description="只返回启用的标签"),
    service: DishService = Depends(get_dish_service),
) -> List[DishTagOut]:
    items = service.list_tags(only_active=only_active)
    return [DishTagOut.model_validate(item) for item in items]


@tag_router.post(
    "", response_model=DishTagOut, status_code=status.HTTP_201_CREATED, summary="新建标签"
)
def create_tag(payload: DishTagCreate, service: DishService = Depends(get_dish_service)) -> DishTag:
    return service.create_tag(payload)


@tag_router.put("/{tag_id}", response_model=DishTagOut, summary="更新标签")
def update_tag(
    tag_id: int, payload: DishTagUpdate, service: DishService = Depends(get_dish_service)
) -> DishTag:
    return service.update_tag(tag_id, payload)


@tag_router.delete("/{tag_id}", response_model=MessageResponse, summary="删除标签")
def delete_tag(tag_id: int, service: DishService = Depends(get_dish_service)) -> MessageResponse:
    service.delete_tag(tag_id)
    return MessageResponse(message="删除成功")


# ==================== 菜品 ====================
@router.get("", response_model=PageResult[DishListItem], summary="菜品列表")
def list_dishes(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="菜名 / 描述模糊搜索"),
    category_id: Optional[int] = Query(None, description="分类筛选"),
    tag_id: Optional[int] = Query(None, description="标签筛选"),
    status_filter: Optional[DishStatus] = Query(None, alias="status", description="售卖状态"),
    is_recommended: Optional[bool] = Query(None, description="是否推荐"),
    low_stock: bool = Query(False, description="只看库存告急（< 10）"),
    service: DishService = Depends(get_dish_service),
) -> PageResult[DishListItem]:
    items, total = service.list_dishes(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        category_id=category_id,
        tag_id=tag_id,
        status=status_filter.value if status_filter else None,
        is_recommended=is_recommended,
        low_stock=low_stock,
    )
    return PageResult.create(
        [DishListItem.model_validate(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.get("/stats", response_model=DishStatsOut, summary="菜品统计与销量排行")
def dish_stats(service: DishService = Depends(get_dish_service)) -> DishStatsOut:
    return DishStatsOut(**service.stats())


@router.post(
    "/upload-image", response_model=UploadOut, summary="上传菜品图片"
)
def upload_dish_image(
    file: UploadFile = File(..., description="菜品图片，支持 jpg/png/webp/gif"),
    service: DishService = Depends(get_dish_service),
) -> UploadOut:
    """上传成功后把返回的 url 写入菜品的 `image` 字段即可。"""
    return UploadOut(**service.upload_image(file))


@router.post("", response_model=DishOut, status_code=status.HTTP_201_CREATED, summary="新建菜品")
def create_dish(
    payload: DishCreate, service: DishService = Depends(get_dish_service)
) -> DishOut:
    """可在同一请求中带上 `specs` 一次创建多个套餐（含价格、库存与售卖规则）。"""
    return DishOut.model_validate(service.create_dish(payload))


@router.get("/{dish_id}", response_model=DishOut, summary="菜品详情")
def get_dish(dish_id: int, service: DishService = Depends(get_dish_service)) -> DishOut:
    return DishOut.model_validate(service.get_dish_or_404(dish_id))


@router.put("/{dish_id}", response_model=DishOut, summary="更新菜品")
def update_dish(
    dish_id: int, payload: DishUpdate, service: DishService = Depends(get_dish_service)
) -> DishOut:
    return DishOut.model_validate(service.update_dish(dish_id, payload))


@router.patch("/{dish_id}/status", response_model=DishOut, summary="上架 / 下架 / 售罄")
def update_dish_status(
    dish_id: int,
    payload: DishStatusUpdate,
    service: DishService = Depends(get_dish_service),
) -> DishOut:
    return DishOut.model_validate(service.set_status(dish_id, payload.status.value))


@router.patch("/{dish_id}/stock", response_model=DishOut, summary="调整库存")
def update_dish_stock(
    dish_id: int,
    payload: DishStockUpdate,
    service: DishService = Depends(get_dish_service),
) -> DishOut:
    """`mode=set` 直接设置库存；`mode=add` 在原库存上增减（补货 / 报损）。"""
    return DishOut.model_validate(service.adjust_stock(dish_id, payload.quantity, payload.mode))


@router.delete("/{dish_id}", response_model=MessageResponse, summary="删除菜品")
def delete_dish(dish_id: int, service: DishService = Depends(get_dish_service)) -> MessageResponse:
    service.delete_dish(dish_id)
    return MessageResponse(message="删除成功")


# ==================== 套餐 / 规格 ====================
@router.get("/{dish_id}/specs", response_model=List[DishSpecOut], summary="套餐列表")
def list_specs(dish_id: int, service: DishService = Depends(get_dish_service)) -> List[DishSpecOut]:
    return [DishSpecOut.model_validate(item) for item in service.list_specs(dish_id)]


@router.post(
    "/{dish_id}/specs",
    response_model=DishSpecOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增套餐",
)
def create_spec(
    dish_id: int, payload: DishSpecCreate, service: DishService = Depends(get_dish_service)
) -> DishSpec:
    return service.create_spec(dish_id, payload)


@router.put("/{dish_id}/specs/{spec_id}", response_model=DishSpecOut, summary="更新套餐")
def update_spec(
    dish_id: int,
    spec_id: int,
    payload: DishSpecUpdate,
    service: DishService = Depends(get_dish_service),
) -> DishSpec:
    return service.update_spec(dish_id, spec_id, payload)


@router.delete(
    "/{dish_id}/specs/{spec_id}", response_model=MessageResponse, summary="删除套餐"
)
def delete_spec(
    dish_id: int, spec_id: int, service: DishService = Depends(get_dish_service)
) -> MessageResponse:
    service.delete_spec(dish_id, spec_id)
    return MessageResponse(message="删除成功")
