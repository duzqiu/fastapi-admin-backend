"""个人简历类目接口（仅管理员可访问）。

这是一个**独立类目**：五组接口各自一个 router / 一个 tag，只依赖自己的服务，
不引用任何其它域的模型、仓储或接口；路径也统一收在 `/resume` 前缀下。

OpenAPI（/docs）里会自成一个类目，下分五组：
    后台-个人简历-个人信息   /resume/personal-infos
    后台-个人简历-教育信息   /resume/educations
    后台-个人简历-工作经历   /resume/work-experiences
    后台-个人简历-项目经历   /resume/projects
    后台-个人简历-自我评价   /resume/evaluations

层级绑定（写入时必填）：
- 教育 / 工作 / 自我评价 绑定 `personal_info_id`（个人信息，即「简历主体」）；
- 项目经历绑定 `work_id`（工作经历，即「公司」），公司名与归属个人由它带出。

五组接口的形状完全一致：分页列表（带关键字搜索）、详情、新增、更新、删除。
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import PageParams, get_current_admin, get_resume_service
from app.models.resume import EducationDegree, ResumeGender
from app.schemas.common import MessageResponse, PageResult, UploadOut
from app.schemas.resume import (
    ResumeEducationCreate,
    ResumeEducationOut,
    ResumeEducationStatusUpdate,
    ResumeEducationUpdate,
    ResumeEvaluationCreate,
    ResumeEvaluationOut,
    ResumeEvaluationStatusUpdate,
    ResumeEvaluationUpdate,
    ResumePersonalInfoCreate,
    ResumePersonalInfoOut,
    ResumePersonalInfoStatusUpdate,
    ResumePersonalInfoUpdate,
    ResumeProjectCreate,
    ResumeProjectOut,
    ResumeProjectStatusUpdate,
    ResumeProjectUpdate,
    ResumeWorkCreate,
    ResumeWorkOut,
    ResumeWorkStatusUpdate,
    ResumeWorkUpdate,
)
from app.services.resume_service import ResumeService

#: 类目统一前缀：五组接口都挂在它下面
RESUME_PREFIX = "/resume"

#: 五组接口共用同一套鉴权（后台管理员）
admin_dependency = [Depends(get_current_admin)]

personal_router = APIRouter(
    prefix=f"{RESUME_PREFIX}/personal-infos",
    tags=["后台-个人简历-个人信息"],
    dependencies=admin_dependency,
)
education_router = APIRouter(
    prefix=f"{RESUME_PREFIX}/educations",
    tags=["后台-个人简历-教育信息"],
    dependencies=admin_dependency,
)
work_router = APIRouter(
    prefix=f"{RESUME_PREFIX}/work-experiences",
    tags=["后台-个人简历-工作经历"],
    dependencies=admin_dependency,
)
project_router = APIRouter(
    prefix=f"{RESUME_PREFIX}/projects",
    tags=["后台-个人简历-项目经历"],
    dependencies=admin_dependency,
)
evaluation_router = APIRouter(
    prefix=f"{RESUME_PREFIX}/evaluations",
    tags=["后台-个人简历-自我评价"],
    dependencies=admin_dependency,
)


# ======================== 个人信息 ========================
@personal_router.get(
    "", response_model=PageResult[ResumePersonalInfoOut], summary="个人信息列表（分页 + 搜索）"
)
def list_personal_infos(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="姓名 / 手机号 / 邮箱 / 城市 / 求职意向模糊搜索"),
    gender: Optional[ResumeGender] = Query(None, description="按性别筛选"),
    is_active: Optional[bool] = Query(None, description="按是否启用筛选"),
    service: ResumeService = Depends(get_resume_service),
) -> PageResult[ResumePersonalInfoOut]:
    items, total = service.list_personal_infos(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        gender=gender.value if gender else None,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@personal_router.post(
    "",
    response_model=ResumePersonalInfoOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增个人信息",
)
def create_personal_info(
    payload: ResumePersonalInfoCreate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumePersonalInfoOut:
    return service.create_personal_info(payload)


# 注意：这条必须放在 `/{info_id}` 之前，否则 `upload-avatar` 会被当成路径参数去解析
@personal_router.post(
    "/upload-avatar", response_model=UploadOut, summary="上传个人头像"
)
def upload_personal_avatar(
    file: UploadFile = File(..., description="头像图片，支持 jpg/png/webp/gif"),
    service: ResumeService = Depends(get_resume_service),
) -> UploadOut:
    """上传成功后把返回的 `url` 写入个人信息的 `avatar` 字段即可。

    新建时可以先上传拿到地址、留在表单里，保存时和其它字段一起提交。
    """
    return UploadOut(**service.upload_avatar(file))


@personal_router.get(
    "/{info_id}", response_model=ResumePersonalInfoOut, summary="个人信息详情"
)
def get_personal_info(
    info_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> ResumePersonalInfoOut:
    return service.get_personal_info(info_id)


@personal_router.put(
    "/{info_id}", response_model=ResumePersonalInfoOut, summary="更新个人信息"
)
def update_personal_info(
    info_id: int,
    payload: ResumePersonalInfoUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumePersonalInfoOut:
    return service.update_personal_info(info_id, payload)


@personal_router.delete(
    "/{info_id}", response_model=MessageResponse, summary="删除个人信息"
)
def delete_personal_info(
    info_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> MessageResponse:
    service.delete_personal_info(info_id)
    return MessageResponse(message="删除成功")


@personal_router.patch(
    "/{info_id}/status",
    response_model=ResumePersonalInfoOut,
    summary="启用 / 禁用个人信息",
)
def update_personal_info_status(
    info_id: int,
    payload: ResumePersonalInfoStatusUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumePersonalInfoOut:
    return service.set_personal_info_status(info_id, payload.is_active)


# ======================== 教育信息 ========================
@education_router.get(
    "", response_model=PageResult[ResumeEducationOut], summary="教育信息列表（分页 + 搜索）"
)
def list_educations(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="姓名 / 学校 / 专业模糊搜索"),
    degree: Optional[EducationDegree] = Query(None, description="按学历筛选"),
    personal_info_id: Optional[int] = Query(None, gt=0, description="只看某个人的教育信息"),
    is_active: Optional[bool] = Query(None, description="按是否启用筛选"),
    service: ResumeService = Depends(get_resume_service),
) -> PageResult[ResumeEducationOut]:
    items, total = service.list_educations(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        degree=degree.value if degree else None,
        personal_info_id=personal_info_id,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@education_router.post(
    "",
    response_model=ResumeEducationOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增教育信息",
)
def create_education(
    payload: ResumeEducationCreate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEducationOut:
    return service.create_education(payload)


@education_router.get(
    "/{education_id}", response_model=ResumeEducationOut, summary="教育信息详情"
)
def get_education(
    education_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEducationOut:
    return service.get_education(education_id)


@education_router.put(
    "/{education_id}", response_model=ResumeEducationOut, summary="更新教育信息"
)
def update_education(
    education_id: int,
    payload: ResumeEducationUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEducationOut:
    return service.update_education(education_id, payload)


@education_router.delete(
    "/{education_id}", response_model=MessageResponse, summary="删除教育信息"
)
def delete_education(
    education_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> MessageResponse:
    service.delete_education(education_id)
    return MessageResponse(message="删除成功")


@education_router.patch(
    "/{education_id}/status",
    response_model=ResumeEducationOut,
    summary="启用 / 禁用教育信息",
)
def update_education_status(
    education_id: int,
    payload: ResumeEducationStatusUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEducationOut:
    return service.set_education_status(education_id, payload.is_active)


# ======================== 工作经历 ========================
@work_router.get(
    "", response_model=PageResult[ResumeWorkOut], summary="工作经历列表（分页 + 搜索）"
)
def list_works(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="姓名 / 公司 / 职位 / 部门模糊搜索"),
    personal_info_id: Optional[int] = Query(None, gt=0, description="只看某个人的工作经历"),
    is_active: Optional[bool] = Query(None, description="按是否启用筛选"),
    service: ResumeService = Depends(get_resume_service),
) -> PageResult[ResumeWorkOut]:
    items, total = service.list_works(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        personal_info_id=personal_info_id,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@work_router.post(
    "",
    response_model=ResumeWorkOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增工作经历",
)
def create_work(
    payload: ResumeWorkCreate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeWorkOut:
    return service.create_work(payload)


@work_router.get("/{work_id}", response_model=ResumeWorkOut, summary="工作经历详情")
def get_work(
    work_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeWorkOut:
    return service.get_work(work_id)


@work_router.put("/{work_id}", response_model=ResumeWorkOut, summary="更新工作经历")
def update_work(
    work_id: int,
    payload: ResumeWorkUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeWorkOut:
    return service.update_work(work_id, payload)


@work_router.delete("/{work_id}", response_model=MessageResponse, summary="删除工作经历")
def delete_work(
    work_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> MessageResponse:
    service.delete_work(work_id)
    return MessageResponse(message="删除成功")


@work_router.patch(
    "/{work_id}/status",
    response_model=ResumeWorkOut,
    summary="启用 / 禁用工作经历",
)
def update_work_status(
    work_id: int,
    payload: ResumeWorkStatusUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeWorkOut:
    return service.set_work_status(work_id, payload.is_active)


# ======================== 项目经历 ========================
@project_router.get(
    "", response_model=PageResult[ResumeProjectOut], summary="项目经历列表（分页 + 搜索）"
)
def list_projects(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="项目名称 / 角色 / 描述模糊搜索"),
    work_id: Optional[int] = Query(None, gt=0, description="只看某段公司经历下的项目"),
    personal_info_id: Optional[int] = Query(None, gt=0, description="只看某个人的项目经历"),
    is_active: Optional[bool] = Query(None, description="按是否启用筛选"),
    service: ResumeService = Depends(get_resume_service),
) -> PageResult[ResumeProjectOut]:
    items, total = service.list_projects(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        work_id=work_id,
        personal_info_id=personal_info_id,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@project_router.post(
    "",
    response_model=ResumeProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增项目经历（必须绑定公司经历）",
)
def create_project(
    payload: ResumeProjectCreate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeProjectOut:
    return service.create_project(payload)


@project_router.get("/{project_id}", response_model=ResumeProjectOut, summary="项目经历详情")
def get_project(
    project_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeProjectOut:
    return service.get_project(project_id)


@project_router.put("/{project_id}", response_model=ResumeProjectOut, summary="更新项目经历")
def update_project(
    project_id: int,
    payload: ResumeProjectUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeProjectOut:
    return service.update_project(project_id, payload)


@project_router.delete("/{project_id}", response_model=MessageResponse, summary="删除项目经历")
def delete_project(
    project_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> MessageResponse:
    service.delete_project(project_id)
    return MessageResponse(message="删除成功")


@project_router.patch(
    "/{project_id}/status",
    response_model=ResumeProjectOut,
    summary="启用 / 禁用项目经历",
)
def update_project_status(
    project_id: int,
    payload: ResumeProjectStatusUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeProjectOut:
    return service.set_project_status(project_id, payload.is_active)


# ======================== 自我评价 ========================
@evaluation_router.get(
    "", response_model=PageResult[ResumeEvaluationOut], summary="自我评价列表（分页 + 搜索）"
)
def list_evaluations(
    page_params: PageParams = Depends(),
    keyword: Optional[str] = Query(None, description="姓名 / 标题 / 内容模糊搜索"),
    personal_info_id: Optional[int] = Query(None, gt=0, description="只看某个人的自我评价"),
    is_active: Optional[bool] = Query(None, description="按是否启用筛选"),
    service: ResumeService = Depends(get_resume_service),
) -> PageResult[ResumeEvaluationOut]:
    items, total = service.list_evaluations(
        page=page_params.page,
        page_size=page_params.page_size,
        keyword=keyword,
        personal_info_id=personal_info_id,
        is_active=is_active,
    )
    return PageResult.create(items, total, page_params.page, page_params.page_size)


@evaluation_router.post(
    "",
    response_model=ResumeEvaluationOut,
    status_code=status.HTTP_201_CREATED,
    summary="新增自我评价",
)
def create_evaluation(
    payload: ResumeEvaluationCreate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEvaluationOut:
    return service.create_evaluation(payload)


@evaluation_router.get(
    "/{evaluation_id}", response_model=ResumeEvaluationOut, summary="自我评价详情"
)
def get_evaluation(
    evaluation_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEvaluationOut:
    return service.get_evaluation(evaluation_id)


@evaluation_router.put(
    "/{evaluation_id}", response_model=ResumeEvaluationOut, summary="更新自我评价"
)
def update_evaluation(
    evaluation_id: int,
    payload: ResumeEvaluationUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEvaluationOut:
    return service.update_evaluation(evaluation_id, payload)


@evaluation_router.delete(
    "/{evaluation_id}", response_model=MessageResponse, summary="删除自我评价"
)
def delete_evaluation(
    evaluation_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> MessageResponse:
    service.delete_evaluation(evaluation_id)
    return MessageResponse(message="删除成功")


@evaluation_router.patch(
    "/{evaluation_id}/status",
    response_model=ResumeEvaluationOut,
    summary="启用 / 禁用自我评价",
)
def update_evaluation_status(
    evaluation_id: int,
    payload: ResumeEvaluationStatusUpdate,
    service: ResumeService = Depends(get_resume_service),
) -> ResumeEvaluationOut:
    return service.set_evaluation_status(evaluation_id, payload.is_active)
