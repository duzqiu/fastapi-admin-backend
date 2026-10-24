"""站内消息服务：写入通知 + 列表 / 未读 / 已读。"""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.message import MemberMessage
from app.repositories.message_repository import MessageRepository


class MessageService:
    """站内消息的业务逻辑。

    通知是「顺手写一条」的旁路：任何写消息失败都不应该让主流程（点赞 / 评论 / 关注）
    跟着失败，所以业务侧调用 `push()` 时统一包一层 try/except。
    """

    #: 摘要最多留多少字，避免消息里塞整段评论
    EXCERPT_LIMIT = 60

    def __init__(self, db: Session) -> None:
        self.db = db
        self.messages = MessageRepository(db)

    # ------------------------- 写入 -------------------------
    def push(
        self,
        recipient_id: Optional[int],
        msg_type: str,
        title: str,
        content: str = "",
        *,
        post_id: Optional[int] = None,
        from_member_id: Optional[int] = None,
        from_nickname: str = "",
    ) -> Optional[MemberMessage]:
        """给某个会员写一条通知；收件人为空（匿名帖 / 未登录）时直接跳过。"""
        if not recipient_id:
            return None

        excerpt = (content or "").strip()
        if len(excerpt) > self.EXCERPT_LIMIT:
            excerpt = excerpt[: self.EXCERPT_LIMIT] + "…"

        message = self.messages.create(
            member_id=int(recipient_id),
            type=msg_type,
            title=(title or "")[:120],
            content=excerpt,
            post_id=post_id,
            from_member_id=from_member_id,
            from_nickname=(from_nickname or "")[:50],
        )
        self.db.commit()
        self.db.refresh(message)
        return message

    # ------------------------- 查询 -------------------------
    def list_messages(
        self, member_id: int, *, page: int = 1, page_size: int = 20
    ) -> Tuple[List[MemberMessage], int]:
        """某个会员的消息列表，最新的在前。"""
        return self.messages.list_for_member(
            member_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    def unread_count(self, member_id: int) -> int:
        """未读条数。"""
        return self.messages.count_unread(member_id)

    # ------------------------- 已读 -------------------------
    def mark_read(self, member_id: int, message_id: int) -> None:
        """标记单条已读（幂等）。"""
        if self.messages.mark_read(member_id, message_id):
            self.db.commit()

    def mark_all_read(self, member_id: int) -> None:
        """全部标记已读（进消息页时调用）。"""
        if self.messages.mark_all_read(member_id):
            self.db.commit()
