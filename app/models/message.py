"""用户中心消息模型：互动通知（点赞 / 评论 / 关注 / 审核结果）。

表名规范：`一级功能_二级功能_功能`
    member_account_message  ->  用户中心_账号_消息
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.core.member_media import resolve_avatar_url
from app.db.base import Base
from app.models.member import Member
from app.models.mixins import PKMixin, TimestampMixin


class MessageType:
    """消息类型（存字符串，App 按它决定图标与点击后的跳转）。"""

    LIKE = "like"                    # 有人赞了我的动态
    COMMENT = "comment"              # 有人评论了我的动态
    FOLLOW = "follow"                # 有人关注了我
    POST_AUDIT = "post_audit"        # 动态审核结果
    COMMENT_AUDIT = "comment_audit"  # 评论审核结果


class MemberMessage(PKMixin, TimestampMixin, Base):
    """站内消息：一条 = 发给某个会员的一条通知。

    标题 / 内容在写入时就拼好（含触发人昵称、动态标题），
    读取时通过只读联表补充触发人的当前头像，避免逐条查询。
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
    # 历史消息表没有外键约束，这里用只读关系补充触发人的头像，不改变表结构。
    from_member: Mapped[Optional[Member]] = relationship(
        Member,
        primaryjoin=lambda: foreign(MemberMessage.from_member_id) == Member.id,
        viewonly=True,
        uselist=False,
        lazy="joined",
    )
    from_nickname: Mapped[str] = mapped_column(
        String(50), default="", comment="触发人昵称快照"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, comment="是否已读"
    )

    @property
    def current_from_nickname(self) -> str:
        """触发人的最新昵称；历史消息没有关联用户时回退到快照。"""
        if self.from_member is not None:
            return self.from_member.display_name
        return self.from_nickname or ""

    @property
    def from_avatar_url(self) -> str:
        """互动消息触发人的头像地址；系统消息没有触发人时返回空串。"""
        if not self.from_member_id or self.from_member is None:
            return ""
        return resolve_avatar_url(self.from_member_id, self.from_member.avatar or "")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<MemberMessage id={self.id} member_id={self.member_id} type={self.type}>"
