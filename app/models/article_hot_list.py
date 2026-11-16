"""热搜榜单（文章板块）：外部榜单（百度 / 微博 ...）抓取下来的条目。

表名按「一级_二级_功能」命名：`article`（文章板块）_ `hot_list` _ `info`，
和 `article_post_info`、`article_official_info` 同属一个板块，不单开一级。

字段刻意与爬虫项目 `scrapy-hotList-crawler` 的 `ScrapyHotlistCrawlerItem`
一一对应，**不做任何加工**，保证「爬到什么就存什么」：

| 爬虫 item 字段 | 本表列 | 说明 |
| --- | --- | --- |
| `source` | `source` | 渠道，如 `baidu`、`weibo` |
| `name` | `name` | 单条热搜的标题（不是榜单名称） |
| `heat` | `heat` | 原始热度文本，如 `"128.6万"`，缺失为 NULL |
| `tabs` | `tabs` | 徽标文字数组，如 `["热"]`，无徽标为 `[]` |
| `rank` | `rank` | 页面展示的排名原样保存，可为 `"1"`、`"置顶"` 等非数字，缺失为 NULL |

`heat` / `rank` 之所以用字符串而不是数字：热度的单位（万 / 亿）和排名的形态
（置顶 / 广告位）都不保证是纯数字，存成数字会丢信息。
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Index, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.utils import utcnow
from app.db.base import Base
from app.models.mixins import PKMixin


class HotListItem(PKMixin, Base):
    """热搜榜单条目：一条 = 某个渠道榜单里的一行。

    没有直接套 `TimestampMixin`：这张表是**外部爬虫写入**的，
    时间列额外带 `server_default`，这样用原生 SQL 插入（不写 created_at /
    updated_at）也能落库，不会因为 NOT NULL 约束失败。
    """

    __tablename__ = "article_hot_list_info"
    __table_args__ = (
        # 「按渠道取整榜」是最热的查询，source 单列索引之外再补一个 (source, id)：
        # 过滤 + 排序都能走同一个索引，翻页不用额外排序。
        Index("ix_article_hot_list_info_source_id", "source", "id"),
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="渠道，例如 baidu、weibo、中国新闻网",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        comment="热搜榜单条目标题（不是榜单名称）",
    )
    heat: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment='原始热度文本，如 "128.6万"；没有热度为 NULL',
    )
    tabs: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment='徽标文字，如 ["热"]、["新"]；没有徽标为 []',
    )
    rank: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment='页面展示的排名原样保存，如 "1"、"置顶"；不展示排名为 NULL',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
        comment="更新时间",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<HotListItem id={self.id} source={self.source!r} "
            f"rank={self.rank!r} name={self.name!r}>"
        )
