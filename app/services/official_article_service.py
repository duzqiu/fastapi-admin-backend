"""Business logic for admin-managed official articles."""

from typing import List, Optional, Tuple, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError, NotFoundError
from app.core.utils import generate_post_no, utcnow
from app.models.member import Member
from app.models.official_article import OfficialArticle, OfficialArticleStatus
from app.repositories.official_article_repository import OfficialArticleRepository
from app.schemas.official_article import OfficialArticleCreate, OfficialArticleUpdate


class OfficialArticleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.articles = OfficialArticleRepository(db)

    def _get(self, article_id: int) -> OfficialArticle:
        item = self.articles.get(article_id)
        if item is None:
            raise NotFoundError(f"官方文章不存在: id={article_id}")
        return item

    def _number(self) -> str:
        for _ in range(10):
            value = generate_post_no()
            if not self.articles.article_no_taken(value):
                return value
        raise BusinessError("文章编号生成失败，请稍后重试")

    def _member(
        self, payload: Union[OfficialArticleCreate, OfficialArticleUpdate]
    ) -> Member:
        """定位发布人：优先用「用户 ID」（member_no），否则退回内部 member_id。"""
        member = None
        if payload.user_id:
            member = (
                self.db.execute(
                    select(Member).where(Member.member_no == payload.user_id.strip())
                )
                .scalars()
                .first()
            )
        elif payload.member_id:
            member = self.db.get(Member, payload.member_id)
        else:
            raise BusinessError("请填写发布人的用户 ID")

        if member is None or not member.is_active:
            raise BusinessError("用户不存在或已被禁用")
        return member

    def _values(self, payload: Union[OfficialArticleCreate, OfficialArticleUpdate], member: Member) -> dict:
        data = payload.model_dump()
        data["url"] = str(data["url"])
        data["image_urls"] = [str(v) for v in data["image_urls"]]
        data["published_at"] = data["published_at"].astimezone()
        data["crawled_at"] = data["crawled_at"].astimezone()
        data["publisher_snapshot"] = member.display_name
        # member_id / user_id 只用于定位发布人，不直接落库
        data.pop("member_id", None)
        data.pop("user_id", None)
        return data

    def create(self, payload: OfficialArticleCreate) -> OfficialArticle:
        member = self._member(payload)
        values = self._values(payload, member)
        item = self.articles.create(article_no=self._number(), member_id=member.id, status=OfficialArticleStatus.PENDING.value, view_count=0, **values)
        self.db.commit(); self.db.refresh(item)
        return item

    def update(self, article_id: int, payload: OfficialArticleUpdate) -> OfficialArticle:
        item = self._get(article_id)
        member = self._member(payload)
        values = self._values(payload, member)
        # Full replacement semantics: optional board/rank must be clearable.
        for field, value in {"member_id": member.id, "status": OfficialArticleStatus.PENDING.value, **values}.items():
            setattr(item, field, value)
        self.db.add(item)
        self.db.flush()
        self.db.commit(); self.db.refresh(item)
        return item

    def get(self, article_id: int) -> OfficialArticle:
        return self._get(article_id)

    def list(self, **kwargs) -> Tuple[List[OfficialArticle], int]:
        return self.articles.search(**kwargs)

    def audit(self, article_id: int, status: OfficialArticleStatus) -> OfficialArticle:
        if status not in (OfficialArticleStatus.APPROVED, OfficialArticleStatus.REJECTED):
            raise BusinessError("审核只能改为 approved 或 rejected")
        item = self._get(article_id)
        if item.status != OfficialArticleStatus.PENDING.value:
            raise BusinessError("该文章已审核，结果不可更改")
        item.status = status.value
        self.db.commit(); self.db.refresh(item)
        return item

    def delete(self, article_id: int) -> None:
        self.articles.delete(self._get(article_id)); self.db.commit()

    def public(self, article_id: int) -> OfficialArticle:
        item = self.articles.get_public(article_id)
        if item is None:
            raise NotFoundError(f"官方文章不存在: id={article_id}")
        return item

    def record_view(self, article_id: int) -> OfficialArticle:
        item = self.public(article_id)
        self.articles.increment_view(item.id)
        self.db.commit(); self.db.refresh(item)
        return item
