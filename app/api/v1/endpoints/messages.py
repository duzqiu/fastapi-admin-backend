"""站内消息接口（App 消息页 / 底部红点，全部需要登录）。

- `GET  /messages`                消息列表（最新在前，分页）
- `GET  /messages/unread-count`   未读数（底部菜单红点）
- `POST /messages/{id}/read`      单条已读
- `POST /messages/read-all`       全部已读（进消息页时调用）

消息由业务侧事件写入（点赞 / 评论 / 关注 / 审核结果），这里只负责读与标记。
"""

from fastapi import APIRouter, Depends

from app.api.deps import PageParams, get_current_member, get_message_service
from app.models.member import Member
from app.schemas.common import MessageResponse, PageResult
from app.schemas.message import MemberMessageOut, UnreadCountOut
from app.services.message_service import MessageService

router = APIRouter(prefix="/messages", tags=["前端-站内消息"])


@router.get("", response_model=PageResult[MemberMessageOut], summary="消息列表（需登录）")
def list_messages(
    page_params: PageParams = Depends(),
    member: Member = Depends(get_current_member),
    service: MessageService = Depends(get_message_service),
) -> PageResult[MemberMessageOut]:
    """当前会员的站内消息，最新的在前。"""
    items, total = service.list_messages(
        member.id,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@router.get(
    "/unread-count",
    response_model=UnreadCountOut,
    summary="未读消息数（需登录）",
)
def get_unread_count(
    member: Member = Depends(get_current_member),
    service: MessageService = Depends(get_message_service),
) -> UnreadCountOut:
    """未读条数，App 用它决定底部「消息」是否显示红点。"""
    return UnreadCountOut(unread_count=service.unread_count(member.id))


@router.post(
    "/read-all", response_model=MessageResponse, summary="全部标记已读（需登录）"
)
def mark_all_read(
    member: Member = Depends(get_current_member),
    service: MessageService = Depends(get_message_service),
) -> MessageResponse:
    """进入消息页后调用：把所有未读一次性标为已读。"""
    service.mark_all_read(member.id)
    return MessageResponse(message="已全部标记为已读")


@router.post(
    "/{message_id}/read", response_model=MessageResponse, summary="单条标记已读（需登录）"
)
def mark_message_read(
    message_id: int,
    member: Member = Depends(get_current_member),
    service: MessageService = Depends(get_message_service),
) -> MessageResponse:
    """标记某条消息已读（幂等；只能标记自己的）。"""
    service.mark_read(member.id, message_id)
    return MessageResponse(message="已标记为已读")
