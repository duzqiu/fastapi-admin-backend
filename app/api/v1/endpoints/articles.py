"""文章管理接口（登录用户可访问）。"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import PageParams, get_article_service, get_current_user
from app.models.article import ArticleStatus
from app.models.user import User
from app.schemas.article import (
    ArticleCreate,
    ArticleListItem,
    ArticleOut,
    ArticleStatusUpdate,
    ArticleUpdate,
)
from app.schemas.common import MessageResponse, PageResult
from app.services.article_service import ArticleService

router = APIRouter(prefix="/articles", tags=["文章管理"])


@router.get("", response_model=PageResult[ArticleListItem], summary="文章列表（分页 + 搜索）")
def list_articles(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="标题/摘要/标签模糊搜索"),
    status_filter: Optional[ArticleStatus] = Query(None, alias="status", description="状态筛选"),
    author_id: Optional[int] = Query(None, description="作者筛选"),
    service: ArticleService = Depends(get_article_service),
    _: User = Depends(get_current_user),
) -> PageResult[ArticleListItem]:
    items, total = service.list_articles(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        status=status_filter.value if status_filter else None,
        author_id=author_id,
    )
    return PageResult.create(
        [ArticleListItem.model_validate(item) for item in items],
        total,
        page_params.page,
        page_params.page_size,
    )


@router.post(
    "",
    response_model=ArticleOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建文章",
)
def create_article(
    payload: ArticleCreate,
    current_user: User = Depends(get_current_user),
    service: ArticleService = Depends(get_article_service),
) -> ArticleOut:
    article = service.create_article(payload, author_id=current_user.id)
    return ArticleOut.model_validate(article)


@router.get("/{article_id}", response_model=ArticleOut, summary="文章详情（浏览量 +1）")
def get_article(
    article_id: int,
    service: ArticleService = Depends(get_article_service),
    _: User = Depends(get_current_user),
) -> ArticleOut:
    return ArticleOut.model_validate(service.get_detail(article_id))


@router.put("/{article_id}", response_model=ArticleOut, summary="更新文章")
def update_article(
    article_id: int,
    payload: ArticleUpdate,
    service: ArticleService = Depends(get_article_service),
    _: User = Depends(get_current_user),
) -> ArticleOut:
    return ArticleOut.model_validate(service.update_article(article_id, payload))


@router.patch("/{article_id}/status", response_model=ArticleOut, summary="修改文章状态")
def update_article_status(
    article_id: int,
    payload: ArticleStatusUpdate,
    service: ArticleService = Depends(get_article_service),
    _: User = Depends(get_current_user),
) -> ArticleOut:
    return ArticleOut.model_validate(service.change_status(article_id, payload.status.value))


@router.delete("/{article_id}", response_model=MessageResponse, summary="删除文章")
def delete_article(
    article_id: int,
    service: ArticleService = Depends(get_article_service),
    _: User = Depends(get_current_user),
) -> MessageResponse:
    service.delete_article(article_id)
    return MessageResponse(message="删除成功")
