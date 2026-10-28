"""站内消息相关 Pydantic 模型。"""

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, Field, computed_field

from app.schemas.common import ORMBaseModel

_TYPE_LABELS = {
    "like": "点赞",
    "comment": "评论",
    "follow": "关注",
    "post_audit": "动态审核",
    "comment_audit": "评论审核",
}


class MemberMessageOut(ORMBaseModel):
    """一条站内消息（App 消息列表用）。"""

    id: int
    type: str
    title: str = ""
    content: str = ""
    post_id: Optional[int] = None
    from_member_id: Optional[int] = None
    from_nickname: str = Field(
        default="",
        validation_alias=AliasChoices("current_from_nickname", "from_nickname"),
        description="触发人当前昵称；无法关联用户时回退为消息快照",
    )
    from_avatar_url: str = Field(default="", description="触发人头像地址；系统消息或触发人不存在时为空")
    is_read: bool = False
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def type_text(self) -> str:
        """消息类型的中文文案（目前只用于后台/调试展示）。"""
        return _TYPE_LABELS.get(self.type, self.type)


class UnreadCountOut(BaseModel):
    """未读消息数（底部菜单红点用）。"""

    unread_count: int = Field(default=0, description="未读消息数")
    counts_by_type: dict[str, int] = Field(
        default_factory=dict, description="按消息类型统计的未读数，无未读的类型可省略"
    )
