"""用户中心消息模型：互动通知（点赞 / 评论 / 关注 / 审核结果）。

表名规范：`一级功能_二级功能_功能`
    member_account_message  ->  用户中心_账号_消息
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class MessageType:
    """消息类型（存字符串，App 按它决定图标与点击后的跳转）。"""

    LIKE = "like"                    # 有人赞了我的帖子
    COMMENT = "comment"              # 有人评论了我的帖子
    FOLLOW = "follow"                # 有人关注了我
    POST_AUDIT = "post_audit"        # 帖子审核结果
    COMMENT_AUDIT = "comment_audit"  # 评论审核结果


class MemberMessage(PKMixin, TimestampMixin, Base):
    """站内消息：一条 = 发给某个会员的一条通知。

    标题 / 内容在写入时就拼好（含触发人昵称、帖子标题），
    读取时不用再联表，列表页一次查询就够。
    """

    __tablename__ = "member_account_message"
    __table_args__ = (
        Index("ix_member_account_message_member_created", "member_id", "created_at"),
        Index("ix_member_account_message_member_read", "member_id", "is_read"),
    )

    member_id: Mapped[int] = mapped_column(
        ForeignKey("member_account_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="收件人（会员）",
    )
    type: Mapped[str] = mapped_column(
        String(20), default=MessageType.LIKE, index=True, comment="消息类型"
    )
    title: Mapped[str] = mapped_column(String(120), default="", comment="标题")
    content: Mapped[str] = mapped_column(Text, default="", comment="正文摘要")
    post_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True, comment="关联帖子 ID（可为空）"
    )
    from_member_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True, comment="触发人会员 ID（可为空）"
    )
    from_nickname: Mapped[str] = mapped_column(
        String(50), default="", comment="触发人昵称快照"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, comment="是否已读"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<MemberMessage id={self.id} member_id={self.member_id} type={self.type}>"
