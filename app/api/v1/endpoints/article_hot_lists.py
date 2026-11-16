"""热搜榜单接口（文章板块的一部分，与动态 / 官号文章 / 评论并列，不单开板块）。

两组路由，职责分开：

- `router`（`/hot-lists`，无需登录）：前台按渠道取榜单，只返回启用中的条目，
  出参固定 `{ source, count, items }` —— `count` 是该渠道启用中的条数；
- `admin_router`（`/hot-lists/admin`，必须管理员）：后台热搜榜单管理，
  列表（全字段，含启用 / 禁用状态）/ 详情 / 编辑 / 删除。

**没有新增接口**：条目由爬虫（`scrapy-hotList-crawler`）写入，
后台刻意不提供「发布」入口。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import PageParams, get_current_admin, get_hot_list_service
from app.schemas.article_hot_list import (
    HotListBoardOut,
    HotListItemOut,
    HotListItemUpdate,
    HotListSourceOut,
)
from app.schemas.common import MessageResponse, PageResult
from app.services.article_hot_list_service import HotListService

router = APIRouter(prefix="/hot-lists", tags=["文章-热搜榜单"])

admin_router = APIRouter(
    prefix="/hot-lists/admin",
    tags=["后台-文章管理-热搜榜单"],
    dependencies=[Depends(get_current_admin)],
)


# ------------------------- 前台 -------------------------
@router.get("", response_model=HotListBoardOut, summary="按渠道取热搜榜单")
def public_board(
    source: str = Query(
        ...,
        min_length=1,
        max_length=50,
        description="榜单渠道，例如 baidu、weibo（精确匹配）",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="最多返回多少条；`count` 仍是该渠道的总条数",
    ),
    svc: HotListService = Depends(get_hot_list_service),
) -> HotListBoardOut:
    """某个渠道的热搜榜单。

    渠道不存在或还没抓到数据时返回空榜单（`count = 0`、`items = []`），
    由前端渲染「暂无数据」，不当成 404。
    """
    items, count = svc.board(source, limit=limit)
    return HotListBoardOut(source=svc.normalize_source(source), count=count, items=items)


@router.get(
    "/sources",
    response_model=List[HotListSourceOut],
    summary="可用渠道及各渠道条数",
)
def public_sources(
    svc: HotListService = Depends(get_hot_list_service),
) -> List[HotListSourceOut]:
    return [
        HotListSourceOut(source=source, count=count) for source, count in svc.sources()
    ]


# ------------------------- 后台（管理员） -------------------------
@admin_router.get(
    "",
    response_model=PageResult[HotListItemOut],
    summary="热搜榜单条目列表（全部字段）",
)
def list_items(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(
        None, description="标题 / 渠道 / 热度 / 排名 模糊搜索"
    ),
    source: Optional[str] = Query(None, max_length=50, description="按渠道精确筛选"),
    is_active: Optional[bool] = Query(
        None, description="按状态筛选：true 启用 / false 禁用；不传返回全部"
    ),
    svc: HotListService = Depends(get_hot_list_service),
):
    items, total = svc.list(
        keyword=keyword,
        source=source,
        is_active=is_active,
        offset=page_params.offset,
        limit=page_params.page_size,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@admin_router.get(
    "/{item_id}", response_model=HotListItemOut, summary="热搜榜单条目详情"
)
def get_item(item_id: int, svc: HotListService = Depends(get_hot_list_service)):
    return svc.get(item_id)


@admin_router.put("/{item_id}", response_model=HotListItemOut, summary="编辑热搜榜单条目")
def update_item(
    item_id: int,
    payload: HotListItemUpdate,
    svc: HotListService = Depends(get_hot_list_service),
):
    """按字段更新：只传要改的字段即可；`heat` / `rank` 传 `null` 表示清空。"""
    return svc.update(item_id, payload)


@admin_router.delete("/{item_id}", response_model=MessageResponse, summary="删除热搜榜单条目")
def delete_item(item_id: int, svc: HotListService = Depends(get_hot_list_service)):
    svc.delete(item_id)
    return MessageResponse(message="删除成功")
