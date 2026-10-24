"""站内消息仓储：列表 / 未读数 / 标记已读。"""

from typing import List, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.message import MemberMessage
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[MemberMessage]):
    """站内消息的数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(MemberMessage, db)

    def list_for_member(
        self, member_id: int, *, offset: int = 0, limit: int = 20
    ) -> Tuple[List[MemberMessage], int]:
        """某个会员的消息列表，最新的在前。"""
        return self.list(
            conditions=[MemberMessage.member_id == member_id],
            order_by=(MemberMessage.created_at.desc(), MemberMessage.id.desc()),
            offset=offset,
            limit=limit,
        )

    def count_unread(self, member_id: int) -> int:
        """未读条数（底部菜单红点用）。"""
        stmt = (
            select(func.count())
            .select_from(MemberMessage)
            .where(
                MemberMessage.member_id == member_id,
                MemberMessage.is_read.is_(False),
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def mark_read(self, member_id: int, message_id: int) -> bool:
        """把一条消息标为已读；返回是否有记录被更新。"""
        stmt = (
            update(MemberMessage)
            .where(
                MemberMessage.id == message_id,
                MemberMessage.member_id == member_id,
                MemberMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        return bool(self.db.execute(stmt).rowcount)

    def mark_all_read(self, member_id: int) -> int:
        """把该会员所有未读消息标为已读，返回更新条数。"""
        stmt = (
            update(MemberMessage)
            .where(
                MemberMessage.member_id == member_id,
                MemberMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        return int(self.db.execute(stmt).rowcount)
