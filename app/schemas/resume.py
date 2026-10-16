"""个人简历相关 Pydantic 模型（接口出入参定义）。

五块数据（个人信息 / 教育信息 / 工作经历 / 项目经历 / 自我评价），
每个都是 `XxxCreate` / `XxxUpdate` / `XxxOut` 三件套。

层级绑定（写入时必填，读出来一并回显）：
- 教育信息 / 工作经历 / 自我评价 通过 `personal_info_id` 绑定「个人信息」；
- 项目经历通过 `work_id` 绑定「工作经历」（公司经历），
  并顺带回显 `personal_info_id` / `owner_name` / `company` / `position`。

`name` 是**简历主体姓名**，由服务层从所属个人信息同步写入，
所以这三个 Create/Update 里都没有 `name`，前端也不用填。
"""

import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.resume import EducationDegree, ResumeGender
from app.schemas.common import ORMBaseModel

#: 「YYYY-MM」月份字段的正则：简历里的入学 / 毕业 / 入职 / 离职时间通常只精确到月
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
MONTH_HINT = "时间格式应为 YYYY-MM，例如 2020-09"


def _clean_month(value: Optional[str]) -> str:
    """校验并规整月份字段：允许空串（未填 / 至今），其余必须是 YYYY-MM。"""
    text = (value or "").strip()
    if text and not re.match(MONTH_PATTERN, text):
        raise ValueError(MONTH_HINT)
    return text


# ------------------------- 个人信息 -------------------------
class ResumePersonalInfoCreate(BaseModel):
    """创建个人信息入参。"""

    name: str = Field(..., min_length=1, max_length=50, description="姓名（简历主体）")
    avatar: str = Field(
        default="", max_length=255, description="头像地址：先调上传接口拿 url，再填进来"
    )
    gender: ResumeGender = Field(default=ResumeGender.SECRET, description="性别")
    birthday: Optional[date] = Field(default=None, description="出生日期")
    phone: str = Field(default="", max_length=20, description="手机号")
    email: str = Field(default="", max_length=120, description="邮箱")
    city: str = Field(default="", max_length=100, description="现居城市")
    job_intention: str = Field(default="", max_length=100, description="求职意向")
    website: str = Field(default="", max_length=200, description="个人主页 / 作品集")
    remark: str = Field(default="", description="备注")
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")


class ResumePersonalInfoUpdate(BaseModel):
    """更新个人信息入参（全部可选，未传字段不修改）。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    avatar: Optional[str] = Field(
        default=None, max_length=255, description="头像地址；传空串表示清空"
    )
    gender: Optional[ResumeGender] = Field(default=None, description="性别")
    birthday: Optional[date] = Field(default=None, description="出生日期")
    phone: Optional[str] = Field(default=None, max_length=20)
    email: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=100)
    job_intention: Optional[str] = Field(default=None, max_length=100)
    website: Optional[str] = Field(default=None, max_length=200)
    remark: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None, description="是否启用")
    sort: Optional[int] = Field(default=None, ge=0)


class ResumePersonalInfoStatusUpdate(BaseModel):
    """启用 / 禁用个人信息。"""

    is_active: bool = Field(..., description="是否启用")


class ResumePersonalInfoOut(ORMBaseModel):
    """个人信息出参。"""

    id: int
    name: str
    avatar: str = Field(default="", description="头像地址，空为未设置")
    gender: str
    gender_text: str = Field(default="", description="性别中文文案")
    birthday: Optional[date] = None
    phone: str = ""
    email: str = ""
    city: str = ""
    job_intention: str = ""
    website: str = ""
    remark: str = ""
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = 0
    created_at: datetime
    updated_at: datetime


# ------------------------- 教育信息 -------------------------
class ResumeEducationCreate(BaseModel):
    """创建教育信息入参。"""

    personal_info_id: int = Field(..., gt=0, description="所属个人信息 ID（必须已存在）")
    school: str = Field(..., min_length=1, max_length=100, description="学校名称")
    major: str = Field(default="", max_length=100, description="专业")
    degree: EducationDegree = Field(
        default=EducationDegree.BACHELOR, description="学历"
    )
    start_month: str = Field(default="", description="入学时间，YYYY-MM")
    end_month: str = Field(default="", description="毕业时间，YYYY-MM")
    description: str = Field(default="", description="在校经历 / 主修课程")
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")

    @field_validator("start_month", "end_month")
    @classmethod
    def check_month(cls, value: Optional[str]) -> str:
        return _clean_month(value)


class ResumeEducationUpdate(BaseModel):
    """更新教育信息入参（全部可选，未传字段不修改）。"""

    personal_info_id: Optional[int] = Field(
        default=None, gt=0, description="改绑到另一个个人信息"
    )
    school: Optional[str] = Field(default=None, min_length=1, max_length=100)
    major: Optional[str] = Field(default=None, max_length=100)
    degree: Optional[EducationDegree] = Field(default=None, description="学历")
    start_month: Optional[str] = Field(default=None, description="入学时间，YYYY-MM")
    end_month: Optional[str] = Field(default=None, description="毕业时间，YYYY-MM")
    description: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None, description="是否启用")
    sort: Optional[int] = Field(default=None, ge=0)

    @field_validator("start_month", "end_month")
    @classmethod
    def check_month(cls, value: Optional[str]) -> str:
        return _clean_month(value)


class ResumeEducationStatusUpdate(BaseModel):
    """启用 / 禁用教育信息。"""

    is_active: bool = Field(..., description="是否启用")


class ResumeEducationOut(ORMBaseModel):
    """教育信息出参。"""

    id: int
    personal_info_id: Optional[int] = Field(default=None, description="所属个人信息 ID")
    name: str
    school: str
    major: str = ""
    degree: str
    degree_text: str = Field(default="", description="学历中文文案")
    start_month: str = ""
    end_month: str = ""
    description: str = ""
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = 0
    created_at: datetime
    updated_at: datetime


# ------------------------- 工作经历 -------------------------
class ResumeWorkCreate(BaseModel):
    """创建工作经历入参。"""

    personal_info_id: int = Field(..., gt=0, description="所属个人信息 ID（必须已存在）")
    company: str = Field(..., min_length=1, max_length=100, description="公司名称")
    position: str = Field(default="", max_length=100, description="职位")
    department: str = Field(default="", max_length=100, description="部门")
    start_month: str = Field(default="", description="入职时间，YYYY-MM")
    end_month: str = Field(default="", description="离职时间，YYYY-MM，空为至今")
    description: str = Field(default="", description="工作内容 / 业绩")
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")

    @field_validator("start_month", "end_month")
    @classmethod
    def check_month(cls, value: Optional[str]) -> str:
        return _clean_month(value)


class ResumeWorkUpdate(BaseModel):
    """更新工作经历入参（全部可选，未传字段不修改）。"""

    personal_info_id: Optional[int] = Field(
        default=None, gt=0, description="改绑到另一个个人信息"
    )
    company: Optional[str] = Field(default=None, min_length=1, max_length=100)
    position: Optional[str] = Field(default=None, max_length=100)
    department: Optional[str] = Field(default=None, max_length=100)
    start_month: Optional[str] = Field(default=None, description="入职时间，YYYY-MM")
    end_month: Optional[str] = Field(default=None, description="离职时间，YYYY-MM")
    description: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None, description="是否启用")
    sort: Optional[int] = Field(default=None, ge=0)

    @field_validator("start_month", "end_month")
    @classmethod
    def check_month(cls, value: Optional[str]) -> str:
        return _clean_month(value)


class ResumeWorkStatusUpdate(BaseModel):
    """启用 / 禁用工作经历。"""

    is_active: bool = Field(..., description="是否启用")


class ResumeWorkOut(ORMBaseModel):
    """工作经历出参。"""

    id: int
    personal_info_id: Optional[int] = Field(default=None, description="所属个人信息 ID")
    name: str
    avatar: str = Field(
        default="", description="所属个人信息的头像地址（随关联带出），空为未设置"
    )
    company: str
    position: str = ""
    department: str = ""
    start_month: str = ""
    end_month: str = ""
    description: str = ""
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = 0
    created_at: datetime
    updated_at: datetime


# ------------------------- 项目经历 -------------------------
class ResumeProjectCreate(BaseModel):
    """创建项目经历入参。"""

    work_id: int = Field(..., gt=0, description="所属工作经历（公司）ID，必须已存在")
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    role: str = Field(default="", max_length=100, description="担任角色")
    start_month: str = Field(default="", description="开始时间，YYYY-MM")
    end_month: str = Field(default="", description="结束时间，YYYY-MM，空为至今")
    description: str = Field(default="", description="项目描述 / 职责 / 业绩")
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")

    @field_validator("start_month", "end_month")
    @classmethod
    def check_month(cls, value: Optional[str]) -> str:
        return _clean_month(value)


class ResumeProjectUpdate(BaseModel):
    """更新项目经历入参（全部可选，未传字段不修改）。"""

    work_id: Optional[int] = Field(
        default=None, gt=0, description="改挂到另一段工作经历（公司）"
    )
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[str] = Field(default=None, max_length=100)
    start_month: Optional[str] = Field(default=None, description="开始时间，YYYY-MM")
    end_month: Optional[str] = Field(default=None, description="结束时间，YYYY-MM")
    description: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None, description="是否启用")
    sort: Optional[int] = Field(default=None, ge=0)

    @field_validator("start_month", "end_month")
    @classmethod
    def check_month(cls, value: Optional[str]) -> str:
        return _clean_month(value)


class ResumeProjectStatusUpdate(BaseModel):
    """启用 / 禁用项目经历。"""

    is_active: bool = Field(..., description="是否启用")


class ResumeProjectOut(ORMBaseModel):
    """项目经历出参（含由所属公司经历带出来的字段）。"""

    id: int
    work_id: int = Field(description="所属工作经历 ID")
    personal_info_id: Optional[int] = Field(
        default=None, description="归属个人信息 ID（由所属公司经历带出）"
    )
    owner_name: str = Field(default="", description="归属个人姓名")
    company: str = Field(default="", description="所属公司名称")
    position: str = Field(default="", description="所属公司职位")
    name: str
    role: str = ""
    start_month: str = ""
    end_month: str = ""
    description: str = ""
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = 0
    created_at: datetime
    updated_at: datetime


# ------------------------- 自我评价 -------------------------
class ResumeEvaluationCreate(BaseModel):
    """创建自我评价入参。"""

    personal_info_id: int = Field(..., gt=0, description="所属个人信息 ID（必须已存在）")
    title: str = Field(default="", max_length=100, description="评价标题")
    content: str = Field(..., min_length=1, description="评价内容")
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")


class ResumeEvaluationUpdate(BaseModel):
    """更新自我评价入参（全部可选，未传字段不修改）。"""

    personal_info_id: Optional[int] = Field(
        default=None, gt=0, description="改绑到另一个个人信息"
    )
    title: Optional[str] = Field(default=None, max_length=100)
    content: Optional[str] = Field(default=None, min_length=1)
    is_active: Optional[bool] = Field(default=None, description="是否启用")
    sort: Optional[int] = Field(default=None, ge=0)


class ResumeEvaluationStatusUpdate(BaseModel):
    """启用 / 禁用自我评价。"""

    is_active: bool = Field(..., description="是否启用")


class ResumeEvaluationOut(ORMBaseModel):
    """自我评价出参。"""

    id: int
    personal_info_id: Optional[int] = Field(default=None, description="所属个人信息 ID")
    name: str
    title: str = ""
    content: str
    is_active: bool = Field(default=True, description="是否启用")
    sort: int = 0
    created_at: datetime
    updated_at: datetime


__all__ = [
    "MONTH_PATTERN",
    "MONTH_HINT",
    "ResumePersonalInfoCreate",
    "ResumePersonalInfoUpdate",
    "ResumePersonalInfoStatusUpdate",
    "ResumePersonalInfoOut",
    "ResumeEducationCreate",
    "ResumeEducationUpdate",
    "ResumeEducationStatusUpdate",
    "ResumeEducationOut",
    "ResumeWorkCreate",
    "ResumeWorkUpdate",
    "ResumeWorkStatusUpdate",
    "ResumeWorkOut",
    "ResumeProjectCreate",
    "ResumeProjectUpdate",
    "ResumeProjectStatusUpdate",
    "ResumeProjectOut",
    "ResumeEvaluationCreate",
    "ResumeEvaluationUpdate",
    "ResumeEvaluationStatusUpdate",
    "ResumeEvaluationOut",
]
