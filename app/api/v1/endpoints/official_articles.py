"""Admin-only official article APIs plus approved public read/view operations."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status as http_status
from sqlalchemy.orm import Session

from app.api.deps import PageParams, get_current_admin
from app.db.session import get_db
from app.models.official_article import OfficialArticleStatus
from app.schemas.common import MessageResponse, PageResult
from app.schemas.official_article import OfficialArticleCreate, OfficialArticleOut, OfficialArticleStatusUpdate, OfficialArticleUpdate
from app.services.official_article_service import OfficialArticleService

router = APIRouter(prefix="/official-articles", tags=["后台-官方文章"], dependencies=[Depends(get_current_admin)])
public_router = APIRouter(prefix="/official-articles", tags=["官方文章-公开"])


def service(db: Session = Depends(get_db)) -> OfficialArticleService:
    return OfficialArticleService(db)


@router.get("", response_model=PageResult[OfficialArticleOut])
def list_articles(page_params: PageParams = Depends(), keyword: Optional[str] = Query(None), status: Optional[OfficialArticleStatus] = Query(None), user_id: Optional[str] = Query(None, description="按「用户 ID」（member_no）筛选"), member_id: Optional[int] = Query(None, ge=1, description="按内部 member_id 筛选（兼容）"), source: Optional[str] = Query(None), svc: OfficialArticleService = Depends(service)):
    items, total = svc.list(keyword=keyword, status=status.value if status else None, member_id=member_id, user_id=user_id, source=source, offset=page_params.offset, limit=page_params.page_size)
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@router.post("", response_model=OfficialArticleOut, status_code=http_status.HTTP_201_CREATED)
def create_article(payload: OfficialArticleCreate, svc: OfficialArticleService = Depends(service)):
    return svc.create(payload)


@router.get("/{article_id}", response_model=OfficialArticleOut)
def get_article(article_id: int, svc: OfficialArticleService = Depends(service)):
    return svc.get(article_id)


@router.put("/{article_id}", response_model=OfficialArticleOut)
def update_article(article_id: int, payload: OfficialArticleUpdate, svc: OfficialArticleService = Depends(service)):
    return svc.update(article_id, payload)


@router.patch("/{article_id}/status", response_model=OfficialArticleOut)
def audit_article(article_id: int, payload: OfficialArticleStatusUpdate, svc: OfficialArticleService = Depends(service)):
    return svc.audit(article_id, payload.status)


@router.delete("/{article_id}", response_model=MessageResponse)
def delete_article(article_id: int, svc: OfficialArticleService = Depends(service)):
    svc.delete(article_id)
    return MessageResponse(message="删除成功")


@public_router.get("/detail/{article_id}", response_model=OfficialArticleOut)
def public_article(article_id: int, db: Session = Depends(get_db)):
    return OfficialArticleService(db).public(article_id)


@public_router.post("/{article_id}/view", response_model=OfficialArticleOut)
def view_article(article_id: int, db: Session = Depends(get_db)):
    return OfficialArticleService(db).record_view(article_id)
