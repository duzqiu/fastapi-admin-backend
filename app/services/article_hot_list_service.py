"""热搜榜单业务逻辑（文章板块，与动态 / 官号文章 / 评论同属一个板块）。

两类调用方：

- 前台：按 `source` 出榜（`board`），另提供可用渠道清单（`sources`）；
- 后台：列表 / 详情 / 编辑 / 删除（`list` / `get` / `update` / `delete`）。

条目的**写入只发生在爬虫侧**（`scrapy-hotList-crawler` 直接写库），
所以这里没有 create —— 后台也没有「发布」入口。
"""

from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, NotFoundError
from app.models.article_hot_list import HotListItem
from app.repositories.article_hot_list_repository import HotListRepository
from app.schemas.article_hot_list import HotListItemUpdate


class HotListService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.items = HotListRepository(db)

    # ------------------------- 前台 -------------------------
    @staticmethod
    def normalize_source(source: Optional[str]) -> str:
        """渠道名去掉首尾空白（渠道是精确匹配的）。"""
        return (source or "").strip()

    def board(
        self, source: str, *, limit: int = 50
    ) -> Tuple[List[HotListItem], int]:
        """按渠道取榜单：返回 (启用中的条目列表, 该渠道启用条数)。

        已从最新榜单消失（`is_active=False`）的条目不对外返回；这些历史数据
        仍保留在库里，后台可以查看和重新启用。
        渠道不存在 / 还没抓到数据时不报错，返回空榜单（`count = 0`）。
        """
        name = self.normalize_source(source)
        if not name:
            raise BusinessError("请传入榜单渠道（source）")
        return self.items.board_page(name, offset=0, limit=limit)

    def sources(self) -> List[Tuple[str, int]]:
        """当前库里有哪些渠道，各自有多少条启用中的条目。"""
        return self.items.source_counts()

    # ------------------------- 后台 -------------------------
    def _get(self, item_id: int) -> HotListItem:
        item = self.items.get(item_id)
        if item is None:
            raise NotFoundError(f"热搜榜单条目不存在: id={item_id}")
        return item

    def list(self, **kwargs) -> Tuple[List[HotListItem], int]:
        return self.items.search(**kwargs)

    def get(self, item_id: int) -> HotListItem:
        return self._get(item_id)

    def update(self, item_id: int, payload: HotListItemUpdate) -> HotListItem:
        """按字段更新：没传的字段保持原值，传 null 表示清空（仅限可空字段）。"""
        item = self._get(item_id)
        values = payload.model_dump(exclude_unset=True)
        # source / name 是 NOT NULL：schemas 已拦 null，这里再兜一层防御
        for field in ("source", "name"):
            if field in values and values[field] is None:
                raise BusinessError(f"{'渠道' if field == 'source' else '标题'}不能为空")
        try:
            item = self.items.apply(item, values)
            self.db.commit()
        except IntegrityError:
            # (source, name) 唯一索引：后台把标题 / 渠道改成已存在的组合时拦住
            self.db.rollback()
            raise BusinessError("同一渠道下已存在同名条目")
        self.db.refresh(item)
        return item

    def delete(self, item_id: int) -> None:
        self.items.delete(self._get(item_id))
        self.db.commit()
