"""菜品服务：分类、标签、菜品、套餐规格与点菜菜单查询。

约定（下单时的定价与库存口径）：
- 菜品**没有套餐**：下单只传 dish_id，价格与库存走菜品自身；
- 菜品**有套餐**：下单必须传 spec_id，价格走套餐，库存需要「菜品总库存」与「套餐库存」同时足够。
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, ConflictError, NotFoundError
from app.core.storage import remove_upload, save_image
from app.models.dish import Dish, DishCategory, DishSpec, DishStatus, DishTag
from app.repositories.dish_repository import (
    DishCategoryRepository,
    DishRepository,
    DishSpecRepository,
    DishTagRepository,
)
from app.schemas.dish import (
    DishCategoryCreate,
    DishCategoryUpdate,
    DishCreate,
    DishSpecCreate,
    DishSpecUpdate,
    DishTagCreate,
    DishTagUpdate,
    DishUpdate,
)

LOW_STOCK_THRESHOLD = 10


class DishService:
    """菜品域业务逻辑（后台管理 + 点菜菜单）。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.categories = DishCategoryRepository(db)
        self.tags = DishTagRepository(db)
        self.dishes = DishRepository(db)
        self.specs = DishSpecRepository(db)

    # ==================== 分类 ====================
    def list_categories(self, *, only_active: bool = False) -> List[DishCategory]:
        items = self.categories.list_all(only_active=only_active)
        counts = self.categories.dish_count_map()
        for item in items:
            item.dish_count = counts.get(item.id, 0)
        return items

    def get_category_or_404(self, category_id: int) -> DishCategory:
        category = self.categories.get(category_id)
        if category is None:
            raise NotFoundError(f"分类不存在: id={category_id}")
        return category

    def create_category(self, payload: DishCategoryCreate) -> DishCategory:
        if self.categories.name_taken(payload.name):
            raise ConflictError(f"分类名称已存在: {payload.name}")
        category = self.categories.create(**payload.model_dump())
        self.db.commit()
        self.db.refresh(category)
        return category

    def update_category(self, category_id: int, payload: DishCategoryUpdate) -> DishCategory:
        category = self.get_category_or_404(category_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("name") and self.categories.name_taken(data["name"], exclude_id=category_id):
            raise ConflictError(f"分类名称已存在: {data['name']}")
        self.categories.update(category, **data)
        self.db.commit()
        self.db.refresh(category)
        return category

    def delete_category(self, category_id: int) -> None:
        category = self.get_category_or_404(category_id)
        used = self.dishes.count(conditions=[Dish.category_id == category_id])
        if used:
            raise BusinessError(f"该分类下还有 {used} 个菜品，请先调整这些菜品的分类")
        self.categories.delete(category)
        self.db.commit()

    # ==================== 标签 ====================
    def list_tags(self) -> List[DishTag]:
        items = self.tags.all_ordered()
        counts = self.tags.dish_count_map()
        for item in items:
            item.dish_count = counts.get(item.id, 0)
        return items

    def get_tag_or_404(self, tag_id: int) -> DishTag:
        tag = self.tags.get(tag_id)
        if tag is None:
            raise NotFoundError(f"标签不存在: id={tag_id}")
        return tag

    def create_tag(self, payload: DishTagCreate) -> DishTag:
        if self.tags.name_taken(payload.name):
            raise ConflictError(f"标签名称已存在: {payload.name}")
        tag = self.tags.create(**payload.model_dump())
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def update_tag(self, tag_id: int, payload: DishTagUpdate) -> DishTag:
        tag = self.get_tag_or_404(tag_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("name") and self.tags.name_taken(data["name"], exclude_id=tag_id):
            raise ConflictError(f"标签名称已存在: {data['name']}")
        self.tags.update(tag, **data)
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def delete_tag(self, tag_id: int) -> None:
        tag = self.get_tag_or_404(tag_id)
        # 先解除与菜品的关联，再删除标签
        tag.dishes.clear()
        self.db.flush()
        self.tags.delete(tag)
        self.db.commit()

    def _resolve_tags(self, tag_ids: Optional[List[int]]) -> List[DishTag]:
        if not tag_ids:
            return []
        tags = self.tags.list_by_ids(tag_ids)
        missing = set(tag_ids) - {tag.id for tag in tags}
        if missing:
            raise BusinessError(f"标签不存在: {sorted(missing)}")
        return tags

    # ==================== 菜品 ====================
    def get_dish_or_404(self, dish_id: int) -> Dish:
        dish = self.dishes.get_with_relations(dish_id)
        if dish is None:
            raise NotFoundError(f"菜品不存在: id={dish_id}")
        return dish

    def list_dishes(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        category_id: Optional[int] = None,
        tag_id: Optional[int] = None,
        status: Optional[str] = None,
        is_recommended: Optional[bool] = None,
        low_stock: bool = False,
    ) -> Tuple[List[Dish], int]:
        return self.dishes.search(
            keyword=keyword,
            category_id=category_id,
            tag_id=tag_id,
            status=status,
            is_recommended=is_recommended,
            low_stock_below=LOW_STOCK_THRESHOLD if low_stock else None,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def create_dish(self, payload: DishCreate) -> Dish:
        if payload.category_id is not None:
            self.get_category_or_404(payload.category_id)
        tags = self._resolve_tags(payload.tag_ids)

        data = payload.model_dump(exclude={"tag_ids", "specs"})
        data["status"] = payload.status.value
        dish = self.dishes.create(**data)
        dish.tags = tags
        self.db.flush()

        for spec_payload in payload.specs:
            self._create_spec(dish, spec_payload)

        self.db.commit()
        self.db.refresh(dish)
        return self.get_dish_or_404(dish.id)

    def update_dish(self, dish_id: int, payload: DishUpdate) -> Dish:
        dish = self.get_dish_or_404(dish_id)
        data = payload.model_dump(exclude_unset=True)

        if "category_id" in data and data["category_id"] is not None:
            self.get_category_or_404(data["category_id"])
        if "status" in data and data["status"] is not None:
            data["status"] = data["status"].value
        if "tag_ids" in data:
            dish.tags = self._resolve_tags(data.pop("tag_ids"))

        self.dishes.update(dish, **data)
        self.db.commit()
        self.db.refresh(dish)
        return self.get_dish_or_404(dish.id)

    def delete_dish(self, dish_id: int) -> None:
        dish = self.get_dish_or_404(dish_id)
        remove_upload(dish.image)
        self.dishes.delete(dish)
        self.db.commit()

    def set_status(self, dish_id: int, status: str) -> Dish:
        dish = self.get_dish_or_404(dish_id)
        self.dishes.update(dish, status=status)
        self.db.commit()
        self.db.refresh(dish)
        return self.get_dish_or_404(dish.id)

    def adjust_stock(self, dish_id: int, quantity: int, mode: str = "set") -> Dish:
        """库存调整：mode=set 直接设置；mode=add 在原库存上增减。"""
        dish = self.get_dish_or_404(dish_id)
        new_stock = quantity if mode == "set" else (dish.stock or 0) + quantity
        if new_stock < 0:
            raise BusinessError(f"库存不能为负数，当前库存 {dish.stock}")
        self.dishes.update(dish, stock=new_stock)
        self.db.commit()
        self.db.refresh(dish)
        return self.get_dish_or_404(dish.id)

    def upload_image(self, upload: UploadFile) -> Dict[str, Any]:
        """上传菜品图片，返回可访问地址（由调用方写入菜品 image 字段）。"""
        return save_image(upload, subdir="dishes", prefix="dish")

    def stats(self) -> Dict[str, Any]:
        """菜品统计概览（含销量排行）。"""
        return {
            "total": self.dishes.count(),
            "on_sale": self.dishes.count_by_status(DishStatus.ON_SALE.value),
            "off_shelf": self.dishes.count_by_status(DishStatus.OFF_SHELF.value),
            "sold_out": self.dishes.count_by_status(DishStatus.SOLD_OUT.value),
            "low_stock": self.dishes.count_low_stock(LOW_STOCK_THRESHOLD),
            "total_sold": self.dishes.total_sold(),
            "category_count": self.categories.count(),
            "tag_count": self.tags.count(),
            "top_selling": [
                {
                    "id": dish.id,
                    "name": dish.name,
                    "image": dish.image,
                    "sold_count": dish.sold_count,
                    "stock": dish.stock,
                }
                for dish in self.dishes.top_selling(5)
            ],
        }

    # ==================== 套餐 / 规格 ====================
    def list_specs(self, dish_id: int) -> List[DishSpec]:
        self.get_dish_or_404(dish_id)
        return self.specs.list_by_dish(dish_id)

    def get_spec_or_404(self, dish_id: int, spec_id: int) -> DishSpec:
        spec = self.specs.get_of_dish(dish_id, spec_id)
        if spec is None:
            raise NotFoundError(f"套餐不存在: dish_id={dish_id}, spec_id={spec_id}")
        return spec

    def _create_spec(self, dish: Dish, payload: DishSpecCreate) -> DishSpec:
        spec = self.specs.create(dish_id=dish.id, **payload.model_dump())
        if spec.is_default or len(dish.specs) <= 1:
            self.specs.clear_default(dish.id, exclude_id=spec.id)
            spec.is_default = True
        return spec

    def create_spec(self, dish_id: int, payload: DishSpecCreate) -> DishSpec:
        dish = self.get_dish_or_404(dish_id)
        spec = self._create_spec(dish, payload)
        self.db.commit()
        self.db.refresh(spec)
        return spec

    def update_spec(self, dish_id: int, spec_id: int, payload: DishSpecUpdate) -> DishSpec:
        dish = self.get_dish_or_404(dish_id)
        spec = self.get_spec_or_404(dish_id, spec_id)

        data = payload.model_dump(exclude_unset=True)
        # 供应时段必须成对出现
        start = data.get("serve_start_time", spec.serve_start_time)
        end = data.get("serve_end_time", spec.serve_end_time)
        if bool(start) != bool(end):
            raise BusinessError("供应开始与结束时间需要同时填写或同时留空")

        self.specs.update(spec, **data)
        if data.get("is_default"):
            self.specs.clear_default(dish.id, exclude_id=spec.id)
            spec.is_default = True
        self.db.commit()
        self.db.refresh(spec)
        return spec

    def delete_spec(self, dish_id: int, spec_id: int) -> None:
        self.get_dish_or_404(dish_id)
        spec = self.get_spec_or_404(dish_id, spec_id)
        self.specs.delete(spec)
        self.db.commit()

    # ==================== 点菜菜单（C 端） ====================
    def menu_categories(self) -> List[DishCategory]:
        """只返回启用且含有在售菜品的分类。"""
        items = self.categories.list_all(only_active=True)
        counts = self.categories.dish_count_map()

        available_counts: Dict[int, int] = {}
        dishes, _ = self.dishes.search(only_available=True, offset=0, limit=10000)
        for dish in dishes:
            if dish.category_id is not None:
                available_counts[dish.category_id] = available_counts.get(dish.category_id, 0) + 1

        result = []
        for item in items:
            item.dish_count = counts.get(item.id, 0)
            item.available_count = available_counts.get(item.id, 0)
            result.append(item)
        return result

    def menu_dishes(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        category_id: Optional[int] = None,
        tag_id: Optional[int] = None,
        is_recommended: Optional[bool] = None,
        include_unavailable: bool = False,
    ) -> Tuple[List[Dish], int]:
        return self.dishes.search(
            keyword=keyword,
            category_id=category_id,
            tag_id=tag_id,
            is_recommended=is_recommended,
            only_available=not include_unavailable,
            offset=(page - 1) * page_size,
            limit=page_size,
            order_by=None,
        )

    def get_menu_dish(self, dish_id: int) -> Dish:
        """点菜详情：仅返回在售菜品。"""
        dish = self.get_dish_or_404(dish_id)
        if dish.status != DishStatus.ON_SALE.value:
            raise BusinessError("该菜品当前不可点单")
        return dish
