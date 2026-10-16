"""个人简历服务：个人信息、教育信息、工作经历、项目经历、自我评价的增删改查。

事务边界：仓储只 flush，commit 统一在本层执行。

层级绑定（本层负责校验，仓储不掺业务判断）：
    个人信息 ─┬─ 教育信息
              ├─ 工作经历 ── 项目经历
              └─ 自我评价

- 写入教育 / 工作 / 自我评价时，`personal_info_id` 必须指向已存在的个人信息，
  并把该个人信息的姓名同步写入 `name`（冗余，便于列表展示与搜索）；
- 写入项目经历时，`work_id` 必须指向已存在的工作经历，公司信息从它带出；
- **删除父级时显式级联删除子级**：库级外键只在全新建库时存在，老库靠
  `schema_sync` 补列是加不上约束的，所以这里不能只依赖数据库的 ondelete。

对外接口（`/resume/public/*`）也收在本层，见类末尾那段：
只读启用数据，并把「一个人的整份简历」一次组装好返回。
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.storage import remove_upload, save_image
from app.models.resume import (
    ResumeEducation,
    ResumeEvaluation,
    ResumePersonalInfo,
    ResumeProject,
    ResumeWork,
)
from app.repositories.resume_repository import (
    ResumeEducationRepository,
    ResumeEvaluationRepository,
    ResumePersonalInfoRepository,
    ResumeProjectRepository,
    ResumeWorkRepository,
)
from app.schemas.resume import (
    ResumeEducationCreate,
    ResumeEducationOut,
    ResumeEducationUpdate,
    ResumeEvaluationCreate,
    ResumeEvaluationOut,
    ResumeEvaluationUpdate,
    ResumePersonalInfoCreate,
    ResumePersonalInfoOut,
    ResumePersonalInfoUpdate,
    ResumeProjectCreate,
    ResumeProjectOut,
    ResumeProjectUpdate,
    ResumeWorkCreate,
    ResumeWorkOut,
    ResumeWorkUpdate,
)
from app.schemas.resume_public import (
    ResumeEducationItem,
    ResumeEvaluationItem,
    ResumePersonalInfoPublicOut,
    ResumeProfileOut,
    ResumeProjectItem,
    ResumeWorkItem,
)

#: 聚合接口取子表时的条数上限。子表已按「本次选中的人」过滤过，
#: 正常一份简历十几条，这里纯粹是防呆，避免异常数据把响应撑爆。
PUBLIC_CHILD_LIMIT = 5000


def _group_by(items: List[Any], attr: str) -> Dict[int, List[Any]]:
    """按某个外键字段分组；列表本身已按 `sort` 排好，分组后各组内部顺序不变。"""
    grouped: Dict[int, List[Any]] = {}
    for item in items:
        grouped.setdefault(getattr(item, attr), []).append(item)
    return grouped


def _build_work_item(work: ResumeWork, projects: List[Any]) -> ResumeWorkItem:
    """把一段公司经历和挂在它下面的项目拼成一条出参。"""
    item = ResumeWorkItem.model_validate(work)
    item.projects = [ResumeProjectItem.model_validate(project) for project in projects]
    return item


class ResumeService:
    """个人简历业务逻辑层（五个子类目共用一个服务）。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.personal_infos = ResumePersonalInfoRepository(db)
        self.educations = ResumeEducationRepository(db)
        self.works = ResumeWorkRepository(db)
        self.projects = ResumeProjectRepository(db)
        self.evaluations = ResumeEvaluationRepository(db)

    # ======================== 关联对象解析（绑定校验） ========================
    def get_personal_info_or_404(self, info_id: int) -> ResumePersonalInfo:
        """取个人信息，不存在直接 404。"""
        item = self.personal_infos.get(info_id)
        if item is None:
            raise NotFoundError(f"个人信息不存在: id={info_id}")
        return item

    def get_work_or_404(self, work_id: int) -> ResumeWork:
        """取工作经历（公司），不存在直接 404。"""
        item = self.works.get(work_id)
        if item is None:
            raise NotFoundError(f"工作经历不存在: id={work_id}")
        return item

    # ======================== 个人信息 ========================
    def list_personal_infos(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        gender: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[ResumePersonalInfoOut], int]:
        """分页查询个人信息。"""
        items, total = self.personal_infos.search(
            keyword=keyword,
            gender=gender,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [ResumePersonalInfoOut.model_validate(item) for item in items], total

    def get_personal_info(self, info_id: int) -> ResumePersonalInfoOut:
        """个人信息详情。"""
        return ResumePersonalInfoOut.model_validate(self.get_personal_info_or_404(info_id))

    def create_personal_info(
        self, payload: ResumePersonalInfoCreate
    ) -> ResumePersonalInfoOut:
        """新增个人信息。"""
        item = self.personal_infos.create(**self._personal_data(payload))
        self.db.commit()
        self.db.refresh(item)
        return ResumePersonalInfoOut.model_validate(item)

    def update_personal_info(
        self, info_id: int, payload: ResumePersonalInfoUpdate
    ) -> ResumePersonalInfoOut:
        """更新个人信息；改了姓名时，子级冗余的 `name` 一并同步。"""
        item = self.get_personal_info_or_404(info_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("gender") is not None:
            data["gender"] = data["gender"].value
        if data.get("name"):
            data["name"] = data["name"].strip()
        # 换了头像就把上一张删掉（`remove_upload` 只认本服务上传的地址，外链会原样忽略）；
        # 显式传 null 视作「清空」，统一成空串，免得被仓储的「None 就跳过」规则挡掉。
        if "avatar" in data and data["avatar"] != item.avatar:
            remove_upload(item.avatar)
            data["avatar"] = (data["avatar"] or "").strip()
        # `birthday` 是这块唯一可空的字段：基座仓储「值为 None 就跳过」，
        # 那是为「没传的字段别动」设计的；但「显式传了 null」在这里是要**清空**，
        # 所以直接落到对象上（随下面那次 flush 一起提交）。
        if "birthday" in data:
            item.birthday = data.pop("birthday")

        self.personal_infos.update(item, **data)
        # 姓名是对外展示的主体字段，子级里冗余存了一份，这里顺手同步
        if "name" in data:
            self.educations.update_name_by_personal_info(info_id, data["name"])
            self.works.update_name_by_personal_info(info_id, data["name"])
            self.evaluations.update_name_by_personal_info(info_id, data["name"])

        self.db.commit()
        self.db.refresh(item)
        return ResumePersonalInfoOut.model_validate(item)

    def delete_personal_info(self, info_id: int) -> None:
        """删除个人信息，并**级联删除**其名下所有子级数据。"""
        item = self.get_personal_info_or_404(info_id)
        # 顺序：先删孙级（项目，挂在工作经历下），再删子级，最后删自己
        self.projects.delete_by_personal_info(info_id)
        self.educations.delete_by_personal_info(info_id)
        self.works.delete_by_personal_info(info_id)
        self.evaluations.delete_by_personal_info(info_id)
        # 头像文件一起清掉（外链会被忽略）
        remove_upload(item.avatar)
        self.personal_infos.delete(item)
        self.db.commit()

    def upload_avatar(self, upload: UploadFile) -> Dict[str, Any]:
        """上传头像，返回可访问地址（由调用方写入个人信息的 `avatar` 字段）。

        与菜品图片同一套路：只负责落盘 + 回地址，不做「传完自动绑定」——
        新建时可以先把地址留在表单里，保存时一起提交。
        """
        return save_image(upload, subdir="resume-avatars", prefix="avatar")

    @staticmethod
    def _personal_data(payload: ResumePersonalInfoCreate) -> dict:
        """入参转落库字段：枚举取值、姓名与头像地址去空格。"""
        data = payload.model_dump()
        data["gender"] = payload.gender.value
        data["name"] = payload.name.strip()
        data["avatar"] = (payload.avatar or "").strip()
        return data

    # ======================== 教育信息 ========================
    def get_education_or_404(self, education_id: int) -> ResumeEducation:
        item = self.educations.get(education_id)
        if item is None:
            raise NotFoundError(f"教育信息不存在: id={education_id}")
        return item

    def list_educations(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        degree: Optional[str] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[ResumeEducationOut], int]:
        """分页查询教育信息。"""
        items, total = self.educations.search(
            keyword=keyword,
            degree=degree,
            personal_info_id=personal_info_id,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [ResumeEducationOut.model_validate(item) for item in items], total

    def get_education(self, education_id: int) -> ResumeEducationOut:
        """教育信息详情。"""
        return ResumeEducationOut.model_validate(self.get_education_or_404(education_id))

    def create_education(self, payload: ResumeEducationCreate) -> ResumeEducationOut:
        """新增教育信息（必须绑定已存在的个人信息）。"""
        personal = self.get_personal_info_or_404(payload.personal_info_id)
        data = payload.model_dump()
        data["name"] = personal.name
        data["degree"] = payload.degree.value
        data["school"] = payload.school.strip()

        item = self.educations.create(**data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeEducationOut.model_validate(item)

    def update_education(
        self, education_id: int, payload: ResumeEducationUpdate
    ) -> ResumeEducationOut:
        """更新教育信息；改绑个人信息时同步姓名。"""
        item = self.get_education_or_404(education_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("degree") is not None:
            data["degree"] = data["degree"].value
        if data.get("school"):
            data["school"] = data["school"].strip()
        if data.get("personal_info_id") is not None:
            data["name"] = self.get_personal_info_or_404(data["personal_info_id"]).name

        self.educations.update(item, **data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeEducationOut.model_validate(item)

    def delete_education(self, education_id: int) -> None:
        """删除教育信息。"""
        self.educations.delete(self.get_education_or_404(education_id))
        self.db.commit()

    # ======================== 工作经历 ========================
    def list_works(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[ResumeWorkOut], int]:
        """分页查询工作经历。"""
        items, total = self.works.search(
            keyword=keyword,
            personal_info_id=personal_info_id,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [ResumeWorkOut.model_validate(item) for item in items], total

    def get_work(self, work_id: int) -> ResumeWorkOut:
        """工作经历详情。"""
        return ResumeWorkOut.model_validate(self.get_work_or_404(work_id))

    def create_work(self, payload: ResumeWorkCreate) -> ResumeWorkOut:
        """新增工作经历（必须绑定已存在的个人信息）。"""
        personal = self.get_personal_info_or_404(payload.personal_info_id)
        data = payload.model_dump()
        data["name"] = personal.name
        data["company"] = payload.company.strip()

        item = self.works.create(**data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeWorkOut.model_validate(item)

    def update_work(self, work_id: int, payload: ResumeWorkUpdate) -> ResumeWorkOut:
        """更新工作经历；改绑个人信息时同步姓名。"""
        item = self.get_work_or_404(work_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("company"):
            data["company"] = data["company"].strip()
        if data.get("personal_info_id") is not None:
            data["name"] = self.get_personal_info_or_404(data["personal_info_id"]).name

        self.works.update(item, **data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeWorkOut.model_validate(item)

    def delete_work(self, work_id: int) -> None:
        """删除工作经历，并**级联删除**挂在这家公司下的项目经历。"""
        item = self.get_work_or_404(work_id)
        self.projects.delete_by_work_ids([work_id])
        self.works.delete(item)
        self.db.commit()

    # ======================== 项目经历 ========================
    def get_project_or_404(self, project_id: int) -> ResumeProject:
        item = self.projects.get(project_id)
        if item is None:
            raise NotFoundError(f"项目经历不存在: id={project_id}")
        return item

    def list_projects(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        work_id: Optional[int] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[ResumeProjectOut], int]:
        """分页查询项目经历（可按公司经历或归属个人筛选）。"""
        items, total = self.projects.search(
            keyword=keyword,
            work_id=work_id,
            personal_info_id=personal_info_id,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [ResumeProjectOut.model_validate(item) for item in items], total

    def get_project(self, project_id: int) -> ResumeProjectOut:
        """项目经历详情。"""
        return ResumeProjectOut.model_validate(self.get_project_or_404(project_id))

    def create_project(self, payload: ResumeProjectCreate) -> ResumeProjectOut:
        """新增项目经历（必须绑定已存在的工作经历 / 公司）。"""
        self.get_work_or_404(payload.work_id)
        data = payload.model_dump()
        data["name"] = payload.name.strip()
        data["role"] = payload.role.strip()

        item = self.projects.create(**data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeProjectOut.model_validate(item)

    def update_project(
        self, project_id: int, payload: ResumeProjectUpdate
    ) -> ResumeProjectOut:
        """更新项目经历；改挂公司时校验目标工作经历存在。"""
        item = self.get_project_or_404(project_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("work_id") is not None:
            self.get_work_or_404(data["work_id"])
        if data.get("name"):
            data["name"] = data["name"].strip()
        if data.get("role") is not None:
            data["role"] = data["role"].strip()

        self.projects.update(item, **data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeProjectOut.model_validate(item)

    def delete_project(self, project_id: int) -> None:
        """删除项目经历。"""
        self.projects.delete(self.get_project_or_404(project_id))
        self.db.commit()

    # ======================== 自我评价 ========================
    def get_evaluation_or_404(self, evaluation_id: int) -> ResumeEvaluation:
        item = self.evaluations.get(evaluation_id)
        if item is None:
            raise NotFoundError(f"自我评价不存在: id={evaluation_id}")
        return item

    def list_evaluations(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        keyword: Optional[str] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[ResumeEvaluationOut], int]:
        """分页查询自我评价。"""
        items, total = self.evaluations.search(
            keyword=keyword,
            personal_info_id=personal_info_id,
            is_active=is_active,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return [ResumeEvaluationOut.model_validate(item) for item in items], total

    def get_evaluation(self, evaluation_id: int) -> ResumeEvaluationOut:
        """自我评价详情。"""
        return ResumeEvaluationOut.model_validate(
            self.get_evaluation_or_404(evaluation_id)
        )

    def create_evaluation(
        self, payload: ResumeEvaluationCreate
    ) -> ResumeEvaluationOut:
        """新增自我评价（必须绑定已存在的个人信息）。"""
        personal = self.get_personal_info_or_404(payload.personal_info_id)
        data = payload.model_dump()
        data["name"] = personal.name
        data["content"] = payload.content.strip()

        item = self.evaluations.create(**data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeEvaluationOut.model_validate(item)

    def update_evaluation(
        self, evaluation_id: int, payload: ResumeEvaluationUpdate
    ) -> ResumeEvaluationOut:
        """更新自我评价；改绑个人信息时同步姓名。"""
        item = self.get_evaluation_or_404(evaluation_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("content"):
            data["content"] = data["content"].strip()
        if data.get("personal_info_id") is not None:
            data["name"] = self.get_personal_info_or_404(data["personal_info_id"]).name

        self.evaluations.update(item, **data)
        self.db.commit()
        self.db.refresh(item)
        return ResumeEvaluationOut.model_validate(item)

    def delete_evaluation(self, evaluation_id: int) -> None:
        """删除自我评价。"""
        self.evaluations.delete(self.get_evaluation_or_404(evaluation_id))
        self.db.commit()


    # ======================== 启用 / 禁用 ========================
    # 「是否启用」只是一条业务标记：不联动父子级（父级停用不代表子级停用），
    # 也不参与任何权限判断，只供列表过滤与前台取数时使用。
    def set_personal_info_status(
        self, info_id: int, is_active: bool
    ) -> ResumePersonalInfoOut:
        """启用 / 禁用个人信息。"""
        item = self.get_personal_info_or_404(info_id)
        self.personal_infos.update(item, is_active=is_active)
        self.db.commit()
        self.db.refresh(item)
        return ResumePersonalInfoOut.model_validate(item)

    def set_education_status(
        self, education_id: int, is_active: bool
    ) -> ResumeEducationOut:
        """启用 / 禁用教育信息。"""
        item = self.get_education_or_404(education_id)
        self.educations.update(item, is_active=is_active)
        self.db.commit()
        self.db.refresh(item)
        return ResumeEducationOut.model_validate(item)

    def set_work_status(self, work_id: int, is_active: bool) -> ResumeWorkOut:
        """启用 / 禁用工作经历。"""
        item = self.get_work_or_404(work_id)
        self.works.update(item, is_active=is_active)
        self.db.commit()
        self.db.refresh(item)
        return ResumeWorkOut.model_validate(item)

    def set_project_status(self, project_id: int, is_active: bool) -> ResumeProjectOut:
        """启用 / 禁用项目经历。"""
        item = self.get_project_or_404(project_id)
        self.projects.update(item, is_active=is_active)
        self.db.commit()
        self.db.refresh(item)
        return ResumeProjectOut.model_validate(item)

    def set_evaluation_status(
        self, evaluation_id: int, is_active: bool
    ) -> ResumeEvaluationOut:
        """启用 / 禁用自我评价。"""
        item = self.get_evaluation_or_404(evaluation_id)
        self.evaluations.update(item, is_active=is_active)
        self.db.commit()
        self.db.refresh(item)
        return ResumeEvaluationOut.model_validate(item)


    # ======================== 对外接口（无需登录，只出启用数据） ========================
    # 对外只保留**一个**聚合接口：一次把「整份简历」取全，省掉前端来回请求。
    # 与后台那套的区别：不鉴权、只查启用数据（含各级父级）、不出内部字段。
    def list_public_profiles(
        self, *, personal_info_id: Optional[int] = None, limit: int = 200
    ) -> List[ResumeProfileOut]:
        """整份简历。

        - 传 `personal_info_id`：只取这个人的（不存在或已停用 → 404）；
        - 不传：取所有启用中的个人，最多 `limit` 个。

        每张子表只查一次再在内存里按归属分组，避免逐个人 N+1 查询。
        """
        persons = self._resolve_public_persons(personal_info_id, limit)
        if not persons:
            return []

        person_ids = [person.id for person in persons]
        educations, _ = self.educations.search_visible(
            personal_info_ids=person_ids, offset=0, limit=PUBLIC_CHILD_LIMIT
        )
        works, _ = self.works.search_visible(
            personal_info_ids=person_ids, offset=0, limit=PUBLIC_CHILD_LIMIT
        )
        work_ids = [work.id for work in works]
        projects: List[ResumeProject] = []
        if work_ids:
            projects, _ = self.projects.search_visible(
                work_ids=work_ids, offset=0, limit=PUBLIC_CHILD_LIMIT
            )
        evaluations, _ = self.evaluations.search_visible(
            personal_info_ids=person_ids, offset=0, limit=PUBLIC_CHILD_LIMIT
        )

        educations_by_person = _group_by(educations, "personal_info_id")
        works_by_person = _group_by(works, "personal_info_id")
        projects_by_work = _group_by(projects, "work_id")
        evaluations_by_person = _group_by(evaluations, "personal_info_id")

        return [
            ResumeProfileOut(
                personal_info=ResumePersonalInfoPublicOut.model_validate(person),
                educations=[
                    ResumeEducationItem.model_validate(item)
                    for item in educations_by_person.get(person.id, [])
                ],
                work_experiences=[
                    _build_work_item(work, projects_by_work.get(work.id, []))
                    for work in works_by_person.get(person.id, [])
                ],
                evaluations=[
                    ResumeEvaluationItem.model_validate(item)
                    for item in evaluations_by_person.get(person.id, [])
                ],
            )
            for person in persons
        ]

    def _resolve_public_persons(
        self, personal_info_id: Optional[int], limit: int
    ) -> List[ResumePersonalInfo]:
        """定出这次要出哪些人：指定了就校验（停用/不存在按 404），否则取全部启用的。"""
        if personal_info_id is None:
            persons, _ = self.personal_infos.search(
                is_active=True, offset=0, limit=limit
            )
            return persons

        person = self.personal_infos.get(personal_info_id)
        if person is None or not person.is_active:
            raise NotFoundError(f"个人信息不存在或未启用: id={personal_info_id}")
        return [person]


__all__ = ["ResumeService"]
