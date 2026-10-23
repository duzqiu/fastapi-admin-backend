"""文章管理接口。

两组路由共用 `/posts` 前缀，但鉴权不同：
- `public_router`：用户发帖（可选登录，带上会员令牌时自动记录发布会员）；
- `router`：后台帖子管理（列表 / 详情 / 审核 / 删除，必须管理员）。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status as http_status

from app.api.deps import (
    PageParams,
    get_current_admin,
    get_current_member,
    get_optional_member,
    get_post_service,
)
from app.models.member import Member
from app.models.post import PostStatus
from app.schemas.common import MessageResponse, PageResult, UploadOut
from app.schemas.post import (
    PostCreate,
    PostOut,
    PostReceivedLikesOut,
    PostStatusUpdate,
    PostUpdate,
)
from app.services.post_service import PostService

router = APIRouter(
    prefix="/posts",
    tags=["后台-文章管理-帖子"],
    dependencies=[Depends(get_current_admin)],
)

public_router = APIRouter(prefix="/posts", tags=["文章-用户发帖"])


# ------------------------- 用户发帖 -------------------------
@public_router.post(
    "",
    response_model=PostOut,
    status_code=http_status.HTTP_201_CREATED,
    summary="用户发帖（默认待审核）",
)
def create_post(
    payload: PostCreate,
    member: Optional[Member] = Depends(get_optional_member),
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """发布后一律进「待审核」，后台审核通过后才对外展示。

    带会员令牌调用时会自动记录 `member_id`，`publisher` 留空则取会员昵称。
    """
    return service.create_post(payload, member)


@public_router.get(
    "/latest",
    response_model=PageResult[PostOut],
    summary="最新已发布帖子（无需登录）",
)
def list_latest_posts(
    page_params: PageParams = Depends(),
    member: Optional[Member] = Depends(get_optional_member),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    """所有已审核通过的帖子，按发布时间倒序 —— 首页「最新」用它。

    不需要登录，也不返回待审核 / 已拒绝的内容；带了会员令牌时，`is_favorited`
    会按该会员的收藏状态返回（未登录恒为 false）。
    """
    items, total = service.list_latest(
        page=page_params.page,
        page_size=page_params.page_size,
        viewer=member,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@public_router.get(
    "/hot",
    response_model=PageResult[PostOut],
    summary="热门帖子（按访问量倒序，无需登录）",
)
def list_hot_posts(
    page_params: PageParams = Depends(),
    member: Optional[Member] = Depends(get_optional_member),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    """所有已审核通过的帖子，按访问量（详情页打开次数）倒序 —— 首页「热门」用它。

    访问量相同再按发布时间倒序；不需要登录，带了会员令牌时 `is_favorited`
    会按该会员的收藏状态返回。
    """
    items, total = service.list_hot(
        page=page_params.page,
        page_size=page_params.page_size,
        viewer=member,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@public_router.get(
    "/recommend",
    response_model=List[PostOut],
    summary="推荐帖子（近一年内随机 10 条，无需登录）",
)
def list_recommend_posts(
    member: Optional[Member] = Depends(get_optional_member),
    service: PostService = Depends(get_post_service),
) -> List[PostOut]:
    """首页「推荐」：从近一年内已审核通过的帖子里随机抽 10 条。

    不分页：每次调用重新随机（条数不足 10 条时有多少给多少）；
    不需要登录，带了会员令牌时 `is_favorited` 会按该会员的收藏状态返回。
    """
    return service.list_recommend(viewer=member)


@public_router.get(
    "/by-member/{member_id}",
    response_model=PageResult[PostOut],
    summary="按会员查询已发布帖子",
)
def list_member_published_posts(
    member_id: int,
    page_params: PageParams = Depends(),
    member: Optional[Member] = Depends(get_optional_member),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    """某个会员的帖子，按发布时间倒序。

    - **本人**（带自己的会员令牌）：待审核 / 已通过 / 已拒绝都返回，
      「我的帖子」才能显示审核状态、并对已拒绝的做修改重提；
    - **访客**（无令牌或不是本人）：只返回已通过的。
    """
    is_owner = member is not None and member.id == member_id
    items, total = service.list_member_posts(
        member_id,
        page=page_params.page,
        page_size=page_params.page_size,
        include_hidden=is_owner,
        viewer=member,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


# ------------------------- 收藏 -------------------------
@public_router.get(
    "/favorites",
    response_model=PageResult[PostOut],
    summary="我收藏的帖子（需登录）",
)
def list_my_favorites(
    page_params: PageParams = Depends(),
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    """当前登录会员收藏的帖子，最近收藏的在前。

    只出已通过审核的；收藏后被拒 / 被删的帖子不再出现。
    """
    items, total = service.list_favorites(
        member.id,
        page=page_params.page,
        page_size=page_params.page_size,
        viewer=member,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@public_router.post(
    "/{post_id}/favorite",
    response_model=PostOut,
    summary="收藏帖子（需登录）",
)
def favorite_post(
    post_id: int,
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """收藏一条已通过的帖子；重复收藏是幂等的。"""
    return service.favorite(post_id, member)


@public_router.delete(
    "/{post_id}/favorite",
    response_model=PostOut,
    summary="取消收藏（需登录）",
)
def unfavorite_post(
    post_id: int,
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """取消收藏；本来就没收藏过也返回成功。"""
    return service.unfavorite(post_id, member)


# ------------------------- 点赞 -------------------------
@public_router.get(
    "/received-likes",
    response_model=PostReceivedLikesOut,
    summary="我的获赞总数（需登录）",
)
def get_received_likes(
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PostReceivedLikesOut:
    """当前登录会员的获赞总数：自己**所有**帖子被点赞的次数合计。

    包含待审核 / 已拒绝的帖子（它们也可能被点过赞）。
    """
    return PostReceivedLikesOut(
        received_like_count=service.received_likes(member.id)
    )


@public_router.get(
    "/received-likes/posts",
    response_model=PageResult[PostOut],
    summary="我获赞的帖子列表（需登录）",
)
def list_received_like_posts(
    page_params: PageParams = Depends(),
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    """「我的」页点「获赞」进的那个列表。

    只出**自己发布且至少收到一个赞**的帖子，按获赞数倒序（相同再按发布时间倒序）；
    每条都带 `like_count` / `is_liked`。
    """
    items, total = service.list_received_like_posts(
        member.id,
        page=page_params.page,
        page_size=page_params.page_size,
        viewer=member,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@public_router.post(
    "/{post_id}/like",
    response_model=PostOut,
    summary="点赞帖子（需登录）",
)
def like_post(
    post_id: int,
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """给一条已通过的帖子点赞；重复点赞是幂等的。"""
    return service.like(post_id, member)


@public_router.delete(
    "/{post_id}/like",
    response_model=PostOut,
    summary="取消点赞（需登录）",
)
def unlike_post(
    post_id: int,
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """取消点赞；本来就没点过也返回成功。"""
    return service.unlike(post_id, member)


# ------------------------- 访问量 -------------------------
@public_router.post(
    "/{post_id}/view",
    response_model=PostOut,
    summary="记录一次访问（详情页打开时调用，无需登录）",
)
def record_post_view(
    post_id: int,
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """帖子被打开一次，访问量 +1，返回带最新 `view_count` 的帖子。

    首页「热门」按这个数字倒序，所以客户端每进一次详情页就调一次。
    """
    return service.record_view(post_id)


@public_router.patch(
    "/{post_id}", response_model=PostOut, summary="修改被拒绝的帖子并重新提交"
)
def resubmit_post(
    post_id: int,
    payload: PostUpdate,
    member: Member = Depends(get_current_member),
    service: PostService = Depends(get_post_service),
) -> PostOut:
    """作者本人修改被拒绝的帖子，提交后状态回到「待审核」等待重新审核。"""
    return service.resubmit(post_id, payload, member)


@public_router.post("/images", response_model=UploadOut, summary="上传帖子图片")
async def upload_post_image(
    file: UploadFile = File(..., description="图片文件（jpg/png/webp/gif，≤ 5MB）"),
    service: PostService = Depends(get_post_service),
) -> UploadOut:
    """只上传图片并返回地址，不绑定帖子。

    发帖时把返回的 `url` 放进 `images` 数组一起提交即可。
    """
    return service.upload_image(file)


# ------------------------- 后台管理 -------------------------
@router.get("", response_model=PageResult[PostOut], summary="帖子列表（分页 + 筛选）")
def list_posts(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="标题 / 正文 / 发布人模糊搜索"),
    status: Optional[PostStatus] = Query(None, description="审核状态筛选"),
    publisher: Optional[str] = Query(None, description="按发布人筛选"),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    items, total = service.list_posts(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        status=status,
        publisher=publisher,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@router.get("/{post_id}", response_model=PostOut, summary="帖子详情")
def get_post(
    post_id: int,
    service: PostService = Depends(get_post_service),
) -> PostOut:
    return service.get_post(post_id)


@router.patch("/{post_id}/status", response_model=PostOut, summary="审核帖子（通过 / 拒绝）")
def audit_post(
    post_id: int,
    payload: PostStatusUpdate,
    service: PostService = Depends(get_post_service),
) -> PostOut:
    return service.audit(post_id, payload.status)


@router.delete("/{post_id}", response_model=MessageResponse, summary="删除帖子")
def delete_post(
    post_id: int,
    service: PostService = Depends(get_post_service),
) -> MessageResponse:
    service.delete_post(post_id)
    return MessageResponse(message="删除成功")
