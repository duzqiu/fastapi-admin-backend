"""文章服务：业务示例模块。"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.article import Article, ArticleStatus
from app.repositories.article_repository import ArticleRepository
from app.schemas.article import ArticleCreate, ArticleUpdate


class ArticleService:
    """文章业务逻辑层。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.articles = ArticleRepository(db)

    # ------------------------- 查询 -------------------------
    def get_or_404(self, article_id: int) -> Article:
        article = self.articles.get(article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: id={article_id}")
        return article

    def get_detail(self, article_id: int) -> Article:
        """查看详情并累加浏览量。"""
        article = self.get_or_404(article_id)
        self.articles.increase_views(article)
        self.db.commit()
        self.db.refresh(article)
        return article

    def list_articles(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        author_id: Optional[int] = None,
    ) -> Tuple[list[Article], int]:
        return self.articles.search(
            keyword=keyword,
            status=status,
            author_id=author_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    # ------------------------- 写入 -------------------------
    def create_article(self, payload: ArticleCreate, author_id: Optional[int]) -> Article:
        article = self.articles.create(
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            tags=payload.tags,
            status=payload.status.value if isinstance(payload.status, ArticleStatus) else payload.status,
            author_id=author_id,
        )
        self.db.commit()
        self.db.refresh(article)
        return article

    def update_article(self, article_id: int, payload: ArticleUpdate) -> Article:
        article = self.get_or_404(article_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("status") is not None:
            data["status"] = (
                data["status"].value if isinstance(data["status"], ArticleStatus) else data["status"]
            )
        self.articles.update(article, **data)
        self.db.commit()
        self.db.refresh(article)
        return article

    def change_status(self, article_id: int, status: str) -> Article:
        article = self.get_or_404(article_id)
        self.articles.update(article, status=status)
        self.db.commit()
        self.db.refresh(article)
        return article

    def delete_article(self, article_id: int) -> None:
        article = self.get_or_404(article_id)
        self.articles.delete(article)
        self.db.commit()
