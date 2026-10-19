"""文章管理接口。

两组路由共用 `/posts` 前缀，但鉴权不同：
- `public_router`：用户发帖（可选登录，带上会员令牌时自动记录发布会员）；
- `router`：后台帖子管理（列表 / 详情 / 审核 / 删除，必须管理员）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status as http_status

from app.api.deps import PageParams, get_current_admin, get_optional_member, get_post_service
from app.models.member import Member
from app.models.post import PostStatus
from app.schemas.common import MessageResponse, PageResult, UploadOut
from app.schemas.post import PostCreate, PostOut, PostStatusUpdate
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
    "/by-member/{member_id}",
    response_model=PageResult[PostOut],
    summary="按会员查询已发布帖子",
)
def list_member_published_posts(
    member_id: int,
    page_params: PageParams = Depends(),
    service: PostService = Depends(get_post_service),
) -> PageResult[PostOut]:
    """某个会员**已发布**的帖子（只返回审核通过的），按发布时间倒序。

    C 端「我的帖子」用它：传当前登录会员的 id 即可。
    """
    items, total = service.list_member_posts(
        member_id, page=page_params.page, page_size=page_params.page_size
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


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
