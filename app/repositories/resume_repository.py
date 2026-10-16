"""个人简历仓储：五张表的查询都集中在这里（本域自分一组，不掺其它域的表）。

列表排序统一 `sort 升序 -> id 升序`：`sort` 归用户自己排，`id` 兜底保证顺序稳定。

层级绑定带来的两个查询诉求，都在这一层解决：
- 教育 / 工作 / 自我评价按 `personal_info_id` 过滤；
- 项目经历按「归属个人信息」过滤时，用子查询把该人名下的工作经历挑出来，
  避免在服务层手写 SQL，也不用把 join 逻辑漏到上层。
"""

from typing import Any, List, Optional, Tuple

from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select, update as sa_update
from sqlalchemy.orm import Session

from app.models.resume import (
    ResumeEducation,
    ResumeEvaluation,
    ResumePersonalInfo,
    ResumeProject,
    ResumeWork,
)
from app.repositories.base import BaseRepository


def _delete_where(db: Session, model: Any, condition: Any) -> int:
    """按条件批量删除，返回删除行数。

    `synchronize_session=False`：不回头刷新 session 里已加载的对象 ——
    调用方（服务层）在这之后会紧接着删父级并 commit，不会再用到这些子对象。
    """
    result = db.execute(
        sa_delete(model).where(condition).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _update_where(db: Session, model: Any, values: dict, condition: Any) -> int:
    """按条件批量更新，返回影响行数（同样不做 session 同步）。"""
    result = db.execute(
        sa_update(model)
        .where(condition)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _active_personal_info_ids() -> Any:
    """「启用中的个人信息」ID 子查询。

    对外接口（`/resume/public/*`）讲的是「这份简历对外可见」，
    所以子级能不能出，要看**自己和父级都启用**：
    父级被停用还漏出子级，前台就会拿到一条没有归属的经历。
    """
    return select(ResumePersonalInfo.id).where(ResumePersonalInfo.is_active.is_(True))


def _active_work_ids() -> Any:
    """「启用中的工作经历」ID 子查询：公司自己启用，且它归属的个人也启用。"""
    return select(ResumeWork.id).where(
        ResumeWork.is_active.is_(True),
        ResumeWork.personal_info_id.in_(_active_personal_info_ids()),
    )


class ResumePersonalInfoRepository(BaseRepository[ResumePersonalInfo]):
    """个人信息数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(ResumePersonalInfo, db)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        gender: Optional[str] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumePersonalInfo], int]:
        """按条件分页搜索个人信息。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    ResumePersonalInfo.name.like(like),
                    ResumePersonalInfo.phone.like(like),
                    ResumePersonalInfo.email.like(like),
                    ResumePersonalInfo.city.like(like),
                    ResumePersonalInfo.job_intention.like(like),
                )
            )
        if gender:
            conditions.append(ResumePersonalInfo.gender == gender)
        if is_active is not None:
            conditions.append(ResumePersonalInfo.is_active == is_active)

        return self.list(
            conditions=conditions,
            order_by=[ResumePersonalInfo.sort.asc(), ResumePersonalInfo.id.asc()],
            offset=offset,
            limit=limit,
        )


class ResumeEducationRepository(BaseRepository[ResumeEducation]):
    """教育信息数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(ResumeEducation, db)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        degree: Optional[str] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeEducation], int]:
        """按条件分页搜索教育信息。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    ResumeEducation.name.like(like),
                    ResumeEducation.school.like(like),
                    ResumeEducation.major.like(like),
                )
            )
        if degree:
            conditions.append(ResumeEducation.degree == degree)
        if personal_info_id:
            conditions.append(ResumeEducation.personal_info_id == personal_info_id)
        if is_active is not None:
            conditions.append(ResumeEducation.is_active == is_active)

        return self.list(
            conditions=conditions,
            order_by=[ResumeEducation.sort.asc(), ResumeEducation.id.asc()],
            offset=offset,
            limit=limit,
        )

    def delete_by_personal_info(self, personal_info_id: int) -> int:
        """删除某个个人信息名下的全部教育信息（级联删除用）。"""
        return _delete_where(
            self.db, ResumeEducation, ResumeEducation.personal_info_id == personal_info_id
        )

    def update_name_by_personal_info(self, personal_info_id: int, name: str) -> int:
        """个人信息改名后，同步其名下教育信息里冗余的姓名。"""
        return _update_where(
            self.db,
            ResumeEducation,
            {"name": name},
            ResumeEducation.personal_info_id == personal_info_id,
        )

    def search_visible(
        self,
        *,
        personal_info_ids: Optional[List[int]] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeEducation], int]:
        """对外接口用：只出「自己启用且归属的个人也启用」的教育信息。

        `personal_info_ids` 传了就再按归属收窄（聚合接口用来一次取一批人的教育经历）。
        """
        conditions: List[Any] = [
            ResumeEducation.is_active.is_(True),
            ResumeEducation.personal_info_id.in_(_active_personal_info_ids()),
        ]
        if personal_info_ids is not None:
            conditions.append(ResumeEducation.personal_info_id.in_(personal_info_ids))

        return self.list(
            conditions=conditions,
            order_by=[ResumeEducation.sort.asc(), ResumeEducation.id.asc()],
            offset=offset,
            limit=limit,
        )


class ResumeWorkRepository(BaseRepository[ResumeWork]):
    """工作经历数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(ResumeWork, db)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeWork], int]:
        """按条件分页搜索工作经历。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    ResumeWork.name.like(like),
                    ResumeWork.company.like(like),
                    ResumeWork.position.like(like),
                    ResumeWork.department.like(like),
                )
            )
        if personal_info_id:
            conditions.append(ResumeWork.personal_info_id == personal_info_id)
        if is_active is not None:
            conditions.append(ResumeWork.is_active == is_active)

        return self.list(
            conditions=conditions,
            order_by=[ResumeWork.sort.asc(), ResumeWork.id.asc()],
            offset=offset,
            limit=limit,
        )

    def delete_by_personal_info(self, personal_info_id: int) -> int:
        """删除某个个人信息名下的全部工作经历（级联删除用）。"""
        return _delete_where(
            self.db, ResumeWork, ResumeWork.personal_info_id == personal_info_id
        )

    def update_name_by_personal_info(self, personal_info_id: int, name: str) -> int:
        """个人信息改名后，同步其名下工作经历里冗余的姓名。"""
        return _update_where(
            self.db,
            ResumeWork,
            {"name": name},
            ResumeWork.personal_info_id == personal_info_id,
        )

    def search_visible(
        self,
        *,
        personal_info_ids: Optional[List[int]] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeWork], int]:
        """对外接口用：只出「自己启用且归属的个人也启用」的工作经历。

        `personal_info_ids` 传了就再按归属收窄（聚合接口用来一次取一批人的工作经历）。
        """
        conditions: List[Any] = [
            ResumeWork.is_active.is_(True),
            ResumeWork.personal_info_id.in_(_active_personal_info_ids()),
        ]
        if personal_info_ids is not None:
            conditions.append(ResumeWork.personal_info_id.in_(personal_info_ids))

        return self.list(
            conditions=conditions,
            order_by=[ResumeWork.sort.asc(), ResumeWork.id.asc()],
            offset=offset,
            limit=limit,
        )


class ResumeProjectRepository(BaseRepository[ResumeProject]):
    """项目经历数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(ResumeProject, db)

    @staticmethod
    def _work_ids_of(personal_info_id: int) -> Any:
        """取某个个人信息名下所有工作经历 ID 的子查询。"""
        return select(ResumeWork.id).where(ResumeWork.personal_info_id == personal_info_id)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        work_id: Optional[int] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeProject], int]:
        """按条件分页搜索项目经历。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    ResumeProject.name.like(like),
                    ResumeProject.role.like(like),
                    ResumeProject.description.like(like),
                )
            )
        if work_id:
            conditions.append(ResumeProject.work_id == work_id)
        if personal_info_id:
            conditions.append(ResumeProject.work_id.in_(self._work_ids_of(personal_info_id)))
        if is_active is not None:
            conditions.append(ResumeProject.is_active == is_active)

        return self.list(
            conditions=conditions,
            order_by=[ResumeProject.sort.asc(), ResumeProject.id.asc()],
            offset=offset,
            limit=limit,
        )

    def delete_by_work_ids(self, work_ids: List[int]) -> int:
        """删除挂在若干段工作经历下的全部项目经历（级联删除用）。"""
        if not work_ids:
            return 0
        return _delete_where(self.db, ResumeProject, ResumeProject.work_id.in_(work_ids))

    def delete_by_personal_info(self, personal_info_id: int) -> int:
        """删除某个个人信息名下（经由其工作经历）的全部项目经历（级联删除用）。"""
        return _delete_where(
            self.db, ResumeProject, ResumeProject.work_id.in_(self._work_ids_of(personal_info_id))
        )

    def search_visible(
        self,
        *,
        work_ids: Optional[List[int]] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeProject], int]:
        """对外接口用：只出「自己启用、所属公司启用、归属个人也启用」的项目经历。

        公司（工作经历）由 `ResumeProject.work` 关联带出，这里只负责把不该露的挡掉。
        `work_ids` 传了就再按公司收窄（聚合接口用它取这批公司下的项目）。
        """
        conditions: List[Any] = [
            ResumeProject.is_active.is_(True),
            ResumeProject.work_id.in_(_active_work_ids()),
        ]
        if work_ids is not None:
            conditions.append(ResumeProject.work_id.in_(work_ids))

        return self.list(
            conditions=conditions,
            order_by=[ResumeProject.sort.asc(), ResumeProject.id.asc()],
            offset=offset,
            limit=limit,
        )


class ResumeEvaluationRepository(BaseRepository[ResumeEvaluation]):
    """自我评价数据访问对象。"""

    def __init__(self, db: Session) -> None:
        super().__init__(ResumeEvaluation, db)

    def search(
        self,
        *,
        keyword: Optional[str] = None,
        personal_info_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeEvaluation], int]:
        """按条件分页搜索自我评价。"""
        conditions: List[Any] = []

        if keyword:
            like = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    ResumeEvaluation.name.like(like),
                    ResumeEvaluation.title.like(like),
                    ResumeEvaluation.content.like(like),
                )
            )
        if personal_info_id:
            conditions.append(ResumeEvaluation.personal_info_id == personal_info_id)
        if is_active is not None:
            conditions.append(ResumeEvaluation.is_active == is_active)

        return self.list(
            conditions=conditions,
            order_by=[ResumeEvaluation.sort.asc(), ResumeEvaluation.id.asc()],
            offset=offset,
            limit=limit,
        )

    def delete_by_personal_info(self, personal_info_id: int) -> int:
        """删除某个个人信息名下的全部自我评价（级联删除用）。"""
        return _delete_where(
            self.db, ResumeEvaluation, ResumeEvaluation.personal_info_id == personal_info_id
        )

    def update_name_by_personal_info(self, personal_info_id: int, name: str) -> int:
        """个人信息改名后，同步其名下自我评价里冗余的姓名。"""
        return _update_where(
            self.db,
            ResumeEvaluation,
            {"name": name},
            ResumeEvaluation.personal_info_id == personal_info_id,
        )

    def search_visible(
        self,
        *,
        personal_info_ids: Optional[List[int]] = None,
        offset: int = 0,
        limit: int = 10,
    ) -> Tuple[List[ResumeEvaluation], int]:
        """对外接口用：只出「自己启用且归属的个人也启用」的自我评价。

        `personal_info_ids` 传了就再按归属收窄（聚合接口用来一次取一批人的自我评价）。
        """
        conditions: List[Any] = [
            ResumeEvaluation.is_active.is_(True),
            ResumeEvaluation.personal_info_id.in_(_active_personal_info_ids()),
        ]
        if personal_info_ids is not None:
            conditions.append(ResumeEvaluation.personal_info_id.in_(personal_info_ids))

        return self.list(
            conditions=conditions,
            order_by=[ResumeEvaluation.sort.asc(), ResumeEvaluation.id.asc()],
            offset=offset,
            limit=limit,
        )


__all__ = [
    "ResumePersonalInfoRepository",
    "ResumeEducationRepository",
    "ResumeWorkRepository",
    "ResumeProjectRepository",
    "ResumeEvaluationRepository",
]
