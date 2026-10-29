"""Validated admin inputs and shared official-article output."""

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, computed_field, field_validator

from app.models.official_article import OfficialArticleStatus
from app.schemas.common import ORMBaseModel


NonblankTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
NonblankContent = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200000)]
NonblankSource = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ArticleURL = Annotated[HttpUrl, Field(max_length=2048)]


class OfficialArticleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: int = Field(..., ge=1, description="Publishing identity: an existing active member")
    url: ArticleURL
    title: NonblankTitle
    content: NonblankContent
    image_urls: List[ArticleURL] = Field(default_factory=list, max_length=50)
    source: NonblankSource
    published_at: AwareDatetime
    crawled_at: AwareDatetime
    board: Optional[str] = Field(default=None, max_length=100)
    rank: Optional[int] = Field(default=None, ge=1)

    @field_validator("board")
    @classmethod
    def strip_board(cls, value):
        return value.strip() if isinstance(value, str) else value


class OfficialArticleUpdate(OfficialArticleCreate):
    """Full PUT replacement; omitted optional fields are cleared."""


class OfficialArticleStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: OfficialArticleStatus

    @field_validator("status")
    @classmethod
    def review_result_only(cls, value):
        if value not in (OfficialArticleStatus.APPROVED, OfficialArticleStatus.REJECTED):
            raise ValueError("审核结果只能是 approved 或 rejected")
        return value


class OfficialArticleOut(ORMBaseModel):
    id: int
    article_no: str
    member_id: Optional[int]
    publisher: str
    publisher_snapshot: str
    url: str
    title: str
    content: str
    image_urls: List[str] = Field(default_factory=list)
    source: str
    published_at: AwareDatetime
    crawled_at: AwareDatetime
    board: Optional[str] = None
    rank: Optional[int] = None
    status: str
    view_count: int = 0
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def status_text(self) -> str:
        return {"pending": "待审核", "approved": "已通过", "rejected": "已拒绝"}.get(self.status, self.status)
