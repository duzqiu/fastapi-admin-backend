"""倒数日服务：倒数日增删改查与统计。

事务边界：仓储只 flush，commit 统一在本层执行。
归属用户是用户中心会员（member_account_info），不是后台账号。
"""

from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.lunar import to_lunar
from app.models.countdown import Countdown
from app.models.member import Member
from app.repositories.countdown_repository import CountdownRepository
from app.schemas.countdown import (
    CountdownCreate,
    CountdownOut,
    CountdownSelfCreate,
    CountdownStatsOut,
    CountdownUpdate,
)


class CountdownService:
    """倒数日业务逻辑层。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.countdowns = CountdownRepository(db)

    # ------------------------- 查询 -------------------------
    def get_or_404(self, countdown_id: int) -> Countdown:
        item = self.countdowns.get(countdown_id)
        if item is None:
            raise NotFoundError(f"倒数日不存在: id={countdown_id}")
        return item

    def get_own_or_404(self, countdown_id: int, member: Member) -> Countdown:
        """取倒数日并校验归属：会员只能操作自己的数据。"""
        item = self.get_or_404(countdown_id)
        if item.member_id != member.id:
            raise ForbiddenError("无权操作他人的倒数日")
        return item

    def list_countdowns(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        member_id: Optional[int] = None,
        cycle: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[CountdownOut], int]:
        items, total = self.countdowns.search(
            keyword=keyword,
            member_id=member_id,
            cycle=cycle,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        members = self._member_map([item.member_id for item in items])
        return [self._to_out(item, members) for item in items], total

    def get_countdown(self, countdown_id: int) -> CountdownOut:
        item = self.get_or_404(countdown_id)
        return self._to_out(item, self._member_map([item.member_id]))

    def stats(self) -> CountdownStatsOut:
        total = self.countdowns.count_all()
        active = self.countdowns.count_active()
        return CountdownStatsOut(total=total, active=active, inactive=total - active)

    # ------------------------- 写入 -------------------------
    def create_countdown(self, payload: CountdownCreate) -> CountdownOut:
        member = self._get_member_or_404(payload.member_id)

        item = self.countdowns.create(
            member_id=member.id,
            title=payload.title.strip(),
            cycle=payload.cycle.value,
            target_date=payload.target_date,
            is_active=payload.is_active,
            remark=payload.remark.strip(),
        )
        self.db.commit()
        self.db.refresh(item)
        return self._to_out(item, {member.id: member})

    def create_for_member(self, member: Member, payload: CountdownSelfCreate) -> CountdownOut:
        """会员自助新增：归属用户固定为当前会员，不接受外部传入 member_id。"""
        data = CountdownCreate(member_id=member.id, **payload.model_dump())
        return self.create_countdown(data)

    def update_countdown(self, countdown_id: int, payload: CountdownUpdate) -> CountdownOut:
        item = self.get_or_404(countdown_id)

        data = payload.model_dump(exclude_unset=True)
        if "title" in data and data["title"]:
            data["title"] = data["title"].strip()
        if "remark" in data and data["remark"] is not None:
            data["remark"] = data["remark"].strip()
        if data.get("cycle") is not None:
            data["cycle"] = data["cycle"].value
        if data.get("member_id") is not None:
            self._get_member_or_404(data["member_id"])

        self.countdowns.update(item, **data)
        self.db.commit()
        self.db.refresh(item)
        return self._to_out(item, self._member_map([item.member_id]))

    def set_status(self, countdown_id: int, is_active: bool) -> CountdownOut:
        item = self.get_or_404(countdown_id)
        self.countdowns.update(item, is_active=is_active)
        self.db.commit()
        self.db.refresh(item)
        return self._to_out(item, self._member_map([item.member_id]))

    def delete_countdown(self, countdown_id: int) -> None:
        item = self.get_or_404(countdown_id)
        self.countdowns.delete(item)
        self.db.commit()

    # ------------------------- 内部辅助 -------------------------
    def _get_member_or_404(self, member_id: int) -> Member:
        member = self.db.get(Member, member_id)
        if member is None:
            raise NotFoundError(f"用户不存在: id={member_id}")
        return member

    def _member_map(self, member_ids: List[int]) -> Dict[int, Member]:
        """批量取归属用户，避免逐条查询造成 N+1。"""
        unique_ids = {mid for mid in member_ids if mid}
        if not unique_ids:
            return {}
        members = self.db.query(Member).filter(Member.id.in_(unique_ids)).all()
        return {member.id: member for member in members}

    def _to_out(self, item: Countdown, members: Dict[int, Member]) -> CountdownOut:
        """组装出参：补上归属用户的用户ID与展示名，以及倒数日当天的农历。"""
        out = CountdownOut.model_validate(item)
        member = members.get(item.member_id)
        out.member_no = member.member_no if member else ""
        out.member_name = member.display_name if member else ""

        lunar = to_lunar(item.next_date)
        out.lunar_text = lunar.text
        out.lunar_festival = lunar.festival
        return out
