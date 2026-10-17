"""个人简历对外接口（前台展示端用，**无需登录**）——只有一个合并接口。

原来按类目拆成五个（个人信息 / 教育 / 工作 / 项目 / 评价），
前端要渲染一份简历得连着发五次请求；现在**合并成一个**：

    GET /resume/public/profiles
        ?personal_info_id=1   只取这个人的整份简历
        （不传）              取所有启用个人的整份简历

一次返回：个人信息 + 教育经历 + 工作经历（每条自带其下的项目经历）+ 自我评价 + 技能标签。

这组接口独立于后台管理端那套（`resume.py`）：

- **路径独立**：统一挂在 `/resume/public` 下，和管理接口 `/resume/*` 并列但互不相干；
- **无需鉴权**：不挂任何认证依赖，任何人可直接访问（与 `/menu` 那套 C 端接口同一套路）；
- **只出启用数据**：记录自己启用，且各级父级也启用
  （条件在仓储的 `search_visible` / `_active_personal_info_ids` 里）；
- **出参独立**：用另一套 schema（`app/schemas/resume_public.py`），
  不含 `is_active`、`sort`、创建时间等内部字段。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_resume_service
from app.schemas.resume_public import ResumeProfileOut
from app.services.resume_service import ResumeService

#: 对外开放前缀，与管理端 `/resume/*` 并列
PUBLIC_PREFIX = "/resume/public"

router = APIRouter(prefix=PUBLIC_PREFIX, tags=["前端-个人简历"])


@router.get(
    "/profiles",
    response_model=List[ResumeProfileOut],
    summary="整份简历（个人信息 + 教育 + 工作含项目 + 自我评价）",
)
def public_profiles(
    personal_info_id: Optional[int] = Query(
        None, gt=0, description="指定「个人信息 ID」只取这个人的；不传则返回所有启用中的人"
    ),
    limit: int = Query(200, ge=1, le=500, description="不传 personal_info_id 时，最多返回多少个人"),
    service: ResumeService = Depends(get_resume_service),
) -> List[ResumeProfileOut]:
    """按个人查询整份简历。

    - 传 `personal_info_id`：返回只含这个人的数组；该个人不存在或已停用 → 404；
    - 不传：返回所有启用中个人的数组（最多 `limit` 个）；

    两种情况返回结构完全一致，都是数组，前端可以按同一套逻辑渲染。
    每个条目的 `work_experiences[].projects[]` 就是这家公司做过的项目；
    `skill_tags[]` 是「标签分类 + 标签数组」，后端已经把分号串拆好，前端直接铺 chip。
    """
    return service.list_public_profiles(personal_info_id=personal_info_id, limit=limit)


__all__ = ["router", "PUBLIC_PREFIX"]
