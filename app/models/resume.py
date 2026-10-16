"""个人简历域 ORM 模型：个人信息、教育信息、工作经历、项目经历、自我评价。

「是否启用」：五张表都有 `is_active`（默认 True）。
它只是一条业务标记（后台可随时开关），**不参与权限、也不影响父子级联**，
列表接口支持按它过滤，便于前台取「只拿启用的数据」。


表名规范：`一级功能_二级功能_功能`
    resume_base_personal_info  ->  个人简历_基础_个人信息
    resume_base_education      ->  个人简历_基础_教育信息
    resume_base_work           ->  个人简历_基础_工作经历
    resume_base_project        ->  个人简历_基础_项目经历
    resume_base_evaluation     ->  个人简历_基础_自我评价

**本域内是一棵树**（个人信息是根）：
    个人信息 ─┬─ 教育信息
              ├─ 工作经历 ── 项目经历（项目挂在某段公司经历下）
              └─ 自我评价

- 教育信息 / 工作经历 / 自我评价 都通过 `personal_info_id` 绑定到个人信息；
- 项目经历通过 `work_id` 绑定到工作经历（因此间接归属到某个个人信息）；
- 删除父级时**由服务层显式级联删除子级**（见 `app/services/resume_service.py`）：
  库级外键只在新建库上存在，老库补列时加不上约束，所以不能只依赖 `ondelete`。

`name` 字段的语义：教育 / 工作 / 自我评价三张表的 `name` 是**简历主体姓名**，
由服务层在写入时从所属个人信息同步过来（冗余存储，便于列表直接展示与搜索）。

时间字段约定：简历里的入学 / 毕业 / 入职 / 离职时间**通常只精确到月**，
所以统一用 `String(7)` 存 `YYYY-MM`（校验在 schemas 层，见 `app/schemas/resume.py`），
比 `Date` 更贴合实际录入习惯，也免去跨库的日期格式差异。
"""

import enum
from datetime import date
from typing import Dict, Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import PKMixin, TimestampMixin


class ResumeGender(str, enum.Enum):
    """个人信息里的性别。"""

    MALE = "male"
    FEMALE = "female"
    SECRET = "secret"


#: 性别取值 -> 中文文案（接口出参的 gender_text 与前端下拉共用）
RESUME_GENDER_LABELS: Dict[str, str] = {
    ResumeGender.MALE.value: "男",
    ResumeGender.FEMALE.value: "女",
    ResumeGender.SECRET.value: "保密",
}


class EducationDegree(str, enum.Enum):
    """教育信息里的学历。"""

    HIGH_SCHOOL = "high_school"  # 高中及以下
    COLLEGE = "college"  # 大专
    BACHELOR = "bachelor"  # 本科
    MASTER = "master"  # 硕士
    DOCTOR = "doctor"  # 博士


#: 学历取值 -> 中文文案
EDUCATION_DEGREE_LABELS: Dict[str, str] = {
    EducationDegree.HIGH_SCHOOL.value: "高中及以下",
    EducationDegree.COLLEGE.value: "大专",
    EducationDegree.BACHELOR.value: "本科",
    EducationDegree.MASTER.value: "硕士",
    EducationDegree.DOCTOR.value: "博士",
}


class ResumePersonalInfo(PKMixin, TimestampMixin, Base):
    """个人信息：简历的「开头那一栏」。"""

    __tablename__ = "resume_base_personal_info"

    name: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="姓名（简历主体）"
    )
    avatar: Mapped[str] = mapped_column(
        String(255), default="", comment="头像地址（上传接口返回的 url，也可填外链）"
    )
    gender: Mapped[str] = mapped_column(
        String(20), default=ResumeGender.SECRET.value, comment="性别：male / female / secret"
    )
    birthday: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="出生日期")
    phone: Mapped[str] = mapped_column(String(20), default="", comment="手机号")
    email: Mapped[str] = mapped_column(String(120), default="", comment="邮箱")
    city: Mapped[str] = mapped_column(String(100), default="", comment="现居城市")
    job_intention: Mapped[str] = mapped_column(String(100), default="", comment="求职意向")
    website: Mapped[str] = mapped_column(String(200), default="", comment="个人主页 / 作品集")
    remark: Mapped[str] = mapped_column(Text, default="", comment="备注")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值，越小越靠前")

    # ------------------------- 派生属性（不落库） -------------------------
    @property
    def gender_text(self) -> str:
        """性别中文文案。"""
        return RESUME_GENDER_LABELS.get(self.gender, self.gender)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ResumePersonalInfo id={self.id} name={self.name!r}>"


class ResumeEducation(PKMixin, TimestampMixin, Base):
    """教育信息：一条 = 一段求学经历，必须绑定到某个个人信息。"""

    __tablename__ = "resume_base_education"

    personal_info_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resume_base_personal_info.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属个人信息 ID（简历主体）；老数据可能为空",
    )
    name: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="姓名（随所属个人信息同步）"
    )
    school: Mapped[str] = mapped_column(String(100), nullable=False, comment="学校名称")
    major: Mapped[str] = mapped_column(String(100), default="", comment="专业")
    degree: Mapped[str] = mapped_column(
        String(20),
        default=EducationDegree.BACHELOR.value,
        comment="学历：high_school / college / bachelor / master / doctor",
    )
    start_month: Mapped[str] = mapped_column(String(7), default="", comment="入学时间，YYYY-MM")
    end_month: Mapped[str] = mapped_column(String(7), default="", comment="毕业时间，YYYY-MM")
    description: Mapped[str] = mapped_column(Text, default="", comment="在校经历 / 主修课程")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值，越小越靠前")

    #: 只读关联（多对一）：出参需要带出所属个人，列表查询时一并 join 出来
    personal_info: Mapped[Optional["ResumePersonalInfo"]] = relationship(
        "ResumePersonalInfo", lazy="joined"
    )

    @property
    def degree_text(self) -> str:
        """学历中文文案。"""
        return EDUCATION_DEGREE_LABELS.get(self.degree, self.degree)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ResumeEducation id={self.id} name={self.name!r} school={self.school!r}>"


class ResumeWork(PKMixin, TimestampMixin, Base):
    """工作经历：一条 = 一段任职经历，必须绑定到某个个人信息。"""

    __tablename__ = "resume_base_work"

    personal_info_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resume_base_personal_info.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属个人信息 ID（简历主体）；老数据可能为空",
    )
    name: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="姓名（随所属个人信息同步）"
    )
    company: Mapped[str] = mapped_column(String(100), nullable=False, comment="公司名称")
    position: Mapped[str] = mapped_column(String(100), default="", comment="职位")
    department: Mapped[str] = mapped_column(String(100), default="", comment="部门")
    start_month: Mapped[str] = mapped_column(String(7), default="", comment="入职时间，YYYY-MM")
    end_month: Mapped[str] = mapped_column(String(7), default="", comment="离职时间，YYYY-MM，空为至今")
    description: Mapped[str] = mapped_column(Text, default="", comment="工作内容 / 业绩")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值，越小越靠前")

    #: 只读关联（多对一）：出参需要带出所属个人
    personal_info: Mapped[Optional["ResumePersonalInfo"]] = relationship(
        "ResumePersonalInfo", lazy="joined"
    )

    # ------------------------- 派生属性（不落库） -------------------------
    @property
    def avatar(self) -> str:
        """所属个人信息的头像地址（只读，随关联带出；没绑定或没设置时为空串）。

        前端「所属公司」下拉要在这个人的名字旁边显示头像，所以随姓名一起带出去。
        """
        return self.personal_info.avatar if self.personal_info else ""

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ResumeWork id={self.id} name={self.name!r} company={self.company!r}>"


class ResumeProject(PKMixin, TimestampMixin, Base):
    """项目经历：一条 = 一段项目经验，必须绑定到某段工作经历（公司）。"""

    __tablename__ = "resume_base_project"

    work_id: Mapped[int] = mapped_column(
        ForeignKey("resume_base_work.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属工作经历 ID（公司经历）",
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="项目名称"
    )
    role: Mapped[str] = mapped_column(String(100), default="", comment="担任角色")
    start_month: Mapped[str] = mapped_column(String(7), default="", comment="开始时间，YYYY-MM")
    end_month: Mapped[str] = mapped_column(String(7), default="", comment="结束时间，YYYY-MM，空为至今")
    description: Mapped[str] = mapped_column(Text, default="", comment="项目描述 / 职责 / 业绩")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值，越小越靠前")

    #: 只读关联（多对一）：公司、职位、归属个人都从这段工作经历上取
    work: Mapped["ResumeWork"] = relationship("ResumeWork", lazy="joined")

    # ------------------------- 派生属性（不落库） -------------------------
    @property
    def personal_info_id(self) -> Optional[int]:
        """归属的个人信息 ID（经由所属工作经历）。"""
        return self.work.personal_info_id if self.work else None

    @property
    def personal_info(self) -> Optional["ResumePersonalInfo"]:
        """归属的个人信息（经由所属工作经历），对外接口直接嵌在出参里。"""
        return self.work.personal_info if self.work else None

    @property
    def owner_name(self) -> str:
        """归属个人姓名（经由所属工作经历）。"""
        return self.work.name if self.work else ""

    @property
    def company(self) -> str:
        """所属工作经历的公司名称。"""
        return self.work.company if self.work else ""

    @property
    def position(self) -> str:
        """所属工作经历的职位。"""
        return self.work.position if self.work else ""

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ResumeProject id={self.id} name={self.name!r} work_id={self.work_id}>"


class ResumeEvaluation(PKMixin, TimestampMixin, Base):
    """自我评价：一条 = 一段自我评价（如「个人优势」「职业规划」），必须绑定个人信息。"""

    __tablename__ = "resume_base_evaluation"

    personal_info_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resume_base_personal_info.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属个人信息 ID（简历主体）；老数据可能为空",
    )
    name: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="姓名（随所属个人信息同步）"
    )
    title: Mapped[str] = mapped_column(String(100), default="", comment="评价标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="评价内容")
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    sort: Mapped[int] = mapped_column(Integer, default=0, comment="排序值，越小越靠前")

    #: 只读关联（多对一）：出参需要带出所属个人
    personal_info: Mapped[Optional["ResumePersonalInfo"]] = relationship(
        "ResumePersonalInfo", lazy="joined"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ResumeEvaluation id={self.id} name={self.name!r} title={self.title!r}>"


__all__ = [
    "ResumePersonalInfo",
    "ResumeEducation",
    "ResumeWork",
    "ResumeProject",
    "ResumeEvaluation",
    "ResumeGender",
    "RESUME_GENDER_LABELS",
    "EducationDegree",
    "EDUCATION_DEGREE_LABELS",
]
