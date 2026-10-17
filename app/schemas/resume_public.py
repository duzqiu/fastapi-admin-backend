"""个人简历对外接口出参（`/resume/public/*`）。

对外只给**一个**聚合接口，一次把「整份简历」取全，省掉前端来回请求：

    GET /resume/public/profiles
        ?personal_info_id=1   只取这个人的
        （不传）              取所有启用个人的

层级关系直接体现在结构里 —— 项目经历就挂在它所属的那段公司经历下面，
所以出参里不再重复回显「项目属于哪家公司」「这条属于哪个人」：

    ResumeProfileOut
      ├─ personal_info               个人信息
      ├─ educations[]                教育经历
      ├─ work_experiences[]          工作经历（公司）
      │    └─ projects[]             在这家公司做过的项目
      ├─ evaluations[]               自我评价
      └─ skill_tags[]                技能标签（分类 + 标签数组）

两点约定：
1. 只输出**启用状态**的数据（记录自己启用，且各级父级也启用）；
2. 不出 `is_active` / `sort` / 创建时间等内部字段，
   列表顺序由接口保证（`sort` 升序），前端按数组顺序渲染即可。
"""

from datetime import date
from typing import List, Optional

from pydantic import Field

from app.schemas.common import ORMBaseModel


class ResumePersonalInfoPublicOut(ORMBaseModel):
    """个人信息（简历主体）。"""

    id: int
    name: str
    avatar: str = Field(default="", description="头像地址，空为未设置")
    gender: str = ""
    gender_text: str = ""
    birthday: Optional[date] = None
    phone: str = ""
    email: str = ""
    city: str = ""
    job_intention: str = ""
    current_status: str = Field(default="", description="目前状态代码")
    current_status_text: str = Field(default="", description="目前状态中文文案")
    website: str = ""
    remark: str = ""


class ResumeEducationItem(ORMBaseModel):
    """教育经历条目。"""

    id: int
    school: str
    major: str = ""
    degree: str = ""
    degree_text: str = ""
    start_month: str = ""
    end_month: str = ""
    description: str = ""


class ResumeEvaluationItem(ORMBaseModel):
    """自我评价条目。"""

    id: int
    title: str = ""
    content: str


class ResumeProjectItem(ORMBaseModel):
    """项目经历条目（嵌在公司经历下面，所以不用再回显公司）。"""

    id: int
    name: str
    role: str = ""
    start_month: str = ""
    end_month: str = ""
    description: str = ""
    duty: str = ""
    achievement: str = ""


class ResumeWorkItem(ORMBaseModel):
    """工作经历条目（公司）+ 挂在这家公司下的项目。"""

    id: int
    company: str
    position: str = ""
    department: str = ""
    start_month: str = ""
    end_month: str = ""
    description: str = ""
    projects: List[ResumeProjectItem] = Field(
        default_factory=list, description="这段公司经历下做过的项目"
    )


class ResumeSkillTagItem(ORMBaseModel):
    """技能标签条目：一个分类 + 该分类下的多个标签（后端已拆好，前端直接铺 chip）。"""

    id: int
    category: str = ""
    tags: List[str] = Field(default_factory=list, description="该分类下的标签列表")


class ResumeProfileOut(ORMBaseModel):
    """一份完整的简历：个人信息 + 教育 + 工作（含项目）+ 自我评价 + 技能标签。"""

    personal_info: ResumePersonalInfoPublicOut
    educations: List[ResumeEducationItem] = Field(default_factory=list, description="教育经历")
    work_experiences: List[ResumeWorkItem] = Field(
        default_factory=list, description="工作经历（每条自带其下的项目经历）"
    )
    evaluations: List[ResumeEvaluationItem] = Field(default_factory=list, description="自我评价")
    skill_tags: List[ResumeSkillTagItem] = Field(
        default_factory=list, description="技能标签（按分类分组，按 sort 升序）"
    )


__all__ = [
    "ResumePersonalInfoPublicOut",
    "ResumeEducationItem",
    "ResumeEvaluationItem",
    "ResumeProjectItem",
    "ResumeWorkItem",
    "ResumeSkillTagItem",
    "ResumeProfileOut",
]
