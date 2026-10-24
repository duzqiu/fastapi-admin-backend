"""个人简历类目测试：个人信息、教育信息、工作经历、项目经历、自我评价、技能标签六组接口。

本类目独立：断言里不涉及任何其它域的数据，全部用带前缀的测试数据以 keyword 隔离。

层级绑定：
    个人信息 ─┬─ 教育信息
              ├─ 工作经历 ── 项目经历
              ├─ 自我评价
              └─ 技能标签
所以除了个人信息本身，其它五组用例都要先建好父级。
"""

API = "/api/v1"
PERSONAL = f"{API}/resume/personal-infos"
EDUCATIONS = f"{API}/resume/educations"
WORKS = f"{API}/resume/work-experiences"
PROJECTS = f"{API}/resume/projects"
EVALUATIONS = f"{API}/resume/evaluations"
SKILLS = f"{API}/resume/skill-tags"

# 测试数据统一带这个前缀，避免与库里已有数据混淆
TAG = "简历测试"

ALL_COLLECTIONS = (PERSONAL, EDUCATIONS, WORKS, PROJECTS, EVALUATIONS, SKILLS)

# 1x1 透明 PNG，用来测头像上传
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


# ==================== 造数小工具 ====================
def create_personal(client, auth_headers, name, **extra):
    """建一个个人信息并返回出参。"""
    payload = {"name": name, **extra}
    response = client.post(PERSONAL, headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_work(client, auth_headers, personal_info_id, company, **extra):
    """建一段工作经历（公司）并返回出参。"""
    payload = {"personal_info_id": personal_info_id, "company": company, **extra}
    response = client.post(WORKS, headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ==================== 鉴权 ====================
def test_requires_admin_token(client):
    """五组接口都必须带后台令牌。"""
    for url in ALL_COLLECTIONS:
        assert client.get(url).status_code == 401


# ==================== 个人信息 ====================
def test_personal_info_crud(client, auth_headers):
    payload = {
        "name": f"{TAG}-张三",
        "gender": "male",
        "birthday": "1996-08-12",
        "phone": "13800001111",
        "email": "zhangsan@example.com",
        "city": "杭州",
        "job_intention": "后端工程师",
        "website": "https://example.com/zhangsan",
        "remark": "测试备注",
        "sort": 1,
    }
    created = client.post(PERSONAL, headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    data = created.json()
    info_id = data["id"]
    assert data["gender_text"] == "男"
    assert data["birthday"] == "1996-08-12"

    # 列表 + 关键字搜索
    listed = client.get(PERSONAL, headers=auth_headers, params={"keyword": TAG})
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == f"{TAG}-张三"

    # 性别筛选：不匹配时查不到
    assert (
        client.get(PERSONAL, headers=auth_headers, params={"keyword": TAG, "gender": "female"}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get(PERSONAL, headers=auth_headers, params={"keyword": TAG, "gender": "male"}).json()[
            "total"
        ]
        == 1
    )

    # 详情
    detail = client.get(f"{PERSONAL}/{info_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["phone"] == "13800001111"

    # 更新（未传字段不动）
    updated = client.put(
        f"{PERSONAL}/{info_id}", headers=auth_headers, json={"city": "上海", "gender": "female"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["city"] == "上海"
    assert updated.json()["gender_text"] == "女"
    assert updated.json()["phone"] == "13800001111"

    # 删除 + 删除后再查 404
    assert client.delete(f"{PERSONAL}/{info_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{PERSONAL}/{info_id}", headers=auth_headers).status_code == 404


def test_personal_info_name_required(client, auth_headers):
    """姓名必填。"""
    response = client.post(PERSONAL, headers=auth_headers, json={"name": ""})
    assert response.status_code == 422


def test_personal_info_birthday_can_be_cleared(client, auth_headers):
    """出生日期是唯一可空字段：显式传 null 要能清掉，没传则不动。"""
    info_id = client.post(
        PERSONAL,
        headers=auth_headers,
        json={"name": f"{TAG}-李四", "birthday": "1990-01-01"},
    ).json()["id"]

    # 没传 birthday -> 保持原值
    unchanged = client.put(
        f"{PERSONAL}/{info_id}", headers=auth_headers, json={"city": "北京"}
    ).json()
    assert unchanged["birthday"] == "1990-01-01"

    # 显式传 null -> 清空
    cleared = client.put(
        f"{PERSONAL}/{info_id}", headers=auth_headers, json={"birthday": None}
    ).json()
    assert cleared["birthday"] is None

    client.delete(f"{PERSONAL}/{info_id}", headers=auth_headers)


def test_personal_info_avatar_upload_and_clear(client, auth_headers):
    """头像：先调上传接口拿 url，写进 avatar 字段；清空时把文件也删掉。"""
    from app.core.config import settings

    info_id = client.post(
        PERSONAL, headers=auth_headers, json={"name": f"{TAG}-头像"}
    ).json()["id"]

    # 上传接口要鉴权
    assert (
        client.post(
            f"{PERSONAL}/upload-avatar",
            files={"file": ("a.png", _PNG, "image/png")},
        ).status_code
        == 401
    )

    uploaded = client.post(
        f"{PERSONAL}/upload-avatar",
        headers=auth_headers,
        files={"file": ("a.png", _PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["url"].startswith(f"{settings.upload_url_prefix}/resume-avatars/")
    assert body["size"] == len(_PNG)

    stored = settings.upload_dir / "resume-avatars" / body["filename"]
    assert stored.is_file(), f"头像应落在 {stored}"
    # 上传目录是静态挂载的，地址能直接取到图片
    assert client.get(body["url"]).content == _PNG

    # 写进个人信息
    saved = client.put(
        f"{PERSONAL}/{info_id}", headers=auth_headers, json={"avatar": body["url"]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["avatar"] == body["url"]

    # 换一张：旧文件被清掉
    again = client.post(
        f"{PERSONAL}/upload-avatar",
        headers=auth_headers,
        files={"file": ("b.png", _PNG, "image/png")},
    ).json()
    client.put(f"{PERSONAL}/{info_id}", headers=auth_headers, json={"avatar": again["url"]})
    assert not stored.is_file(), "换头像时上一张应被删除"

    # 删个人信息时头像文件一起走
    assert client.delete(f"{PERSONAL}/{info_id}", headers=auth_headers).status_code == 200
    assert not (settings.upload_dir / "resume-avatars" / again["filename"]).is_file()


def test_personal_info_avatar_rejects_non_image(client, auth_headers):
    """非图片内容 / 不支持的扩展名都按业务错误 400 返回。"""
    assert (
        client.post(
            f"{PERSONAL}/upload-avatar",
            headers=auth_headers,
            files={"file": ("a.png", b"not-an-image", "image/png")},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"{PERSONAL}/upload-avatar",
            headers=auth_headers,
            files={"file": ("a.txt", _PNG, "text/plain")},
        ).status_code
        == 400
    )


def test_personal_info_rename_syncs_children(client, auth_headers):
    """改名后，名下的教育 / 工作 / 自我评价里冗余的姓名一并同步。"""
    person = create_personal(client, auth_headers, f"{TAG}-改名前")
    person_id = person["id"]

    education = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "school": f"{TAG}改名大学"},
    ).json()
    work = create_work(client, auth_headers, person_id, f"{TAG}改名公司")
    evaluation = client.post(
        EVALUATIONS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "content": "改名前的评价"},
    ).json()

    assert education["name"] == f"{TAG}-改名前"
    assert work["name"] == f"{TAG}-改名前"
    assert evaluation["name"] == f"{TAG}-改名前"

    renamed = client.put(
        f"{PERSONAL}/{person_id}", headers=auth_headers, json={"name": f"{TAG}-改名后"}
    )
    assert renamed.status_code == 200, renamed.text

    assert (
        client.get(f"{EDUCATIONS}/{education['id']}", headers=auth_headers).json()["name"]
        == f"{TAG}-改名后"
    )
    assert (
        client.get(f"{WORKS}/{work['id']}", headers=auth_headers).json()["name"]
        == f"{TAG}-改名后"
    )
    assert (
        client.get(f"{EVALUATIONS}/{evaluation['id']}", headers=auth_headers).json()["name"]
        == f"{TAG}-改名后"
    )

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


# ==================== 教育信息 ====================
def test_education_crud(client, auth_headers):
    person_id = create_personal(client, auth_headers, f"{TAG}-教育张三")["id"]

    payload = {
        "personal_info_id": person_id,
        "school": f"{TAG}大学",
        "major": "计算机科学与技术",
        "degree": "bachelor",
        "start_month": "2014-09",
        "end_month": "2018-06",
        "description": "主修数据库、操作系统",
        "sort": 2,
    }
    created = client.post(EDUCATIONS, headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    data = created.json()
    education_id = data["id"]
    assert data["degree_text"] == "本科"
    # 姓名由所属个人信息带出，前端不用填
    assert data["name"] == f"{TAG}-教育张三"
    assert data["personal_info_id"] == person_id

    listed = client.get(EDUCATIONS, headers=auth_headers, params={"keyword": TAG})
    assert listed.json()["total"] == 1

    # 学历筛选
    assert (
        client.get(
            EDUCATIONS, headers=auth_headers, params={"keyword": TAG, "degree": "master"}
        ).json()["total"]
        == 0
    )

    # 按归属个人筛选
    assert (
        client.get(
            EDUCATIONS, headers=auth_headers, params={"personal_info_id": person_id}
        ).json()["total"]
        == 1
    )

    updated = client.put(
        f"{EDUCATIONS}/{education_id}",
        headers=auth_headers,
        json={"degree": "master", "end_month": "2021-06"},
    )
    assert updated.status_code == 200
    assert updated.json()["degree_text"] == "硕士"

    assert client.delete(f"{EDUCATIONS}/{education_id}", headers=auth_headers).status_code == 200
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_education_requires_existing_personal(client, auth_headers):
    """绑定不存在的个人信息 -> 404；绑定字段缺失 -> 422。"""
    missing = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={"personal_info_id": 999999, "school": f"{TAG}野鸡大学"},
    )
    assert missing.status_code == 404
    assert "个人信息不存在" in missing.text

    # 不再接受只传姓名（必须显式绑定）
    unbound = client.post(
        EDUCATIONS, headers=auth_headers, json={"name": f"{TAG}-张三", "school": "某校"}
    )
    assert unbound.status_code == 422


def test_education_month_format(client, auth_headers):
    """入学 / 毕业时间只接受 YYYY-MM；空串表示未填。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-月格式")["id"]

    bad = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={
            "personal_info_id": person_id,
            "school": "某校",
            "start_month": "2014/09",
        },
    )
    assert bad.status_code == 422
    assert "YYYY-MM" in bad.text

    ok = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={
            "personal_info_id": person_id,
            "school": "某校",
            "start_month": "",
            "end_month": "",
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["start_month"] == ""

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_education_rebind_personal(client, auth_headers):
    """改绑到另一个人时，姓名跟着换。"""
    alice_id = create_personal(client, auth_headers, f"{TAG}-换绑甲")["id"]
    bob_id = create_personal(client, auth_headers, f"{TAG}-换绑乙")["id"]

    education = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={"personal_info_id": alice_id, "school": f"{TAG}换绑大学"},
    ).json()

    rebound = client.put(
        f"{EDUCATIONS}/{education['id']}",
        headers=auth_headers,
        json={"personal_info_id": bob_id},
    )
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["personal_info_id"] == bob_id
    assert rebound.json()["name"] == f"{TAG}-换绑乙"

    client.delete(f"{PERSONAL}/{alice_id}", headers=auth_headers)
    client.delete(f"{PERSONAL}/{bob_id}", headers=auth_headers)


# ==================== 工作经历 ====================
def test_work_crud(client, auth_headers):
    person_id = create_personal(client, auth_headers, f"{TAG}-工作张三")["id"]

    payload = {
        "personal_info_id": person_id,
        "company": f"{TAG}科技有限公司",
        "position": "后端开发工程师",
        "department": "平台研发部",
        "start_month": "2018-07",
        "end_month": "",
        "description": "负责订单系统",
        "sort": 3,
    }
    created = client.post(WORKS, headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    work = created.json()
    work_id = work["id"]
    assert work["name"] == f"{TAG}-工作张三"
    assert work["personal_info_id"] == person_id

    listed = client.get(WORKS, headers=auth_headers, params={"keyword": "科技有限公司"})
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["end_month"] == ""

    updated = client.put(
        f"{WORKS}/{work_id}",
        headers=auth_headers,
        json={"position": "高级后端开发工程师", "end_month": "2022-03"},
    )
    assert updated.status_code == 200
    assert updated.json()["position"] == "高级后端开发工程师"

    assert client.delete(f"{WORKS}/{work_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{WORKS}/{work_id}", headers=auth_headers).status_code == 404
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_work_requires_existing_personal(client, auth_headers):
    """公司经历也必须绑定已存在的个人信息。"""
    response = client.post(
        WORKS,
        headers=auth_headers,
        json={"personal_info_id": 999999, "company": f"{TAG}幽灵公司"},
    )
    assert response.status_code == 404
    assert "个人信息不存在" in response.text


def test_work_out_carries_owner_avatar(client, auth_headers):
    """工作出参带上「所属个人」的头像：前端「所属公司」下拉要在姓名旁显示它。"""
    person = create_personal(
        client, auth_headers, f"{TAG}-公司头像", avatar="https://cdn.example.com/w.png"
    )
    work = create_work(client, auth_headers, person["id"], f"{TAG}头像公司")

    # 新建、详情、列表三处都随关联带出
    assert work["avatar"] == "https://cdn.example.com/w.png"
    assert (
        client.get(f"{WORKS}/{work['id']}", headers=auth_headers).json()["avatar"]
        == "https://cdn.example.com/w.png"
    )
    items = client.get(
        WORKS, headers=auth_headers, params={"personal_info_id": person["id"]}
    ).json()["items"]
    assert items[0]["avatar"] == "https://cdn.example.com/w.png"

    # 个人信息换了头像后再查公司经历，拿到的是新头像（跟姓名不同，这里不做落库快照）
    client.put(
        f"{PERSONAL}/{person['id']}",
        headers=auth_headers,
        json={"avatar": "https://cdn.example.com/w2.png"},
    )
    assert (
        client.get(f"{WORKS}/{work['id']}", headers=auth_headers).json()["avatar"]
        == "https://cdn.example.com/w2.png"
    )

    client.delete(f"{PERSONAL}/{person['id']}", headers=auth_headers)


# ==================== 项目经历 ====================
def test_project_crud(client, auth_headers):
    person_id = create_personal(client, auth_headers, f"{TAG}-项目张三")["id"]
    work = create_work(
        client, auth_headers, person_id, f"{TAG}项目公司", position="技术专家"
    )

    payload = {
        "work_id": work["id"],
        "name": f"{TAG}订单中台",
        "role": "后端负责人",
        "start_month": "2020-03",
        "end_month": "2021-12",
        "description": "拆分单体订单服务，支撑日均 200 万单",
        "duty": "负责订单服务的拆分与灰度上线",
        "achievement": "下单接口 P99 从 800ms 降到 220ms",
        "sort": 1,
    }
    created = client.post(PROJECTS, headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    data = created.json()
    project_id = data["id"]
    # 公司 / 归属个人由所属公司经历带出
    assert data["company"] == f"{TAG}项目公司"
    assert data["position"] == "技术专家"
    assert data["personal_info_id"] == person_id
    assert data["owner_name"] == f"{TAG}-项目张三"
    # 职责 / 业绩独立存放，不再塞进描述里
    assert data["duty"] == "负责订单服务的拆分与灰度上线"
    assert data["achievement"] == "下单接口 P99 从 800ms 降到 220ms"

    # 列表 + 关键字（职责、业绩也参与匹配）
    listed = client.get(PROJECTS, headers=auth_headers, params={"keyword": "订单中台"})
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["company"] == f"{TAG}项目公司"
    assert (
        client.get(PROJECTS, headers=auth_headers, params={"keyword": "P99"}).json()["total"]
        == 1
    )

    # 按公司经历过滤
    assert (
        client.get(PROJECTS, headers=auth_headers, params={"work_id": work["id"]}).json()["total"]
        == 1
    )
    # 按归属个人过滤
    assert (
        client.get(
            PROJECTS, headers=auth_headers, params={"personal_info_id": person_id}
        ).json()["total"]
        == 1
    )

    updated = client.put(
        f"{PROJECTS}/{project_id}",
        headers=auth_headers,
        json={"role": "项目负责人", "end_month": ""},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == "项目负责人"
    assert updated.json()["end_month"] == ""

    assert client.delete(f"{PROJECTS}/{project_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{PROJECTS}/{project_id}", headers=auth_headers).status_code == 404
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_project_requires_existing_work(client, auth_headers):
    """项目经历必须绑定已存在的公司经历。"""
    response = client.post(
        PROJECTS,
        headers=auth_headers,
        json={"work_id": 999999, "name": f"{TAG}幽灵项目"},
    )
    assert response.status_code == 404
    assert "工作经历不存在" in response.text

    # 不传 work_id -> 422
    assert (
        client.post(
            PROJECTS, headers=auth_headers, json={"name": f"{TAG}无主项目"}
        ).status_code
        == 422
    )


def test_project_move_to_another_work(client, auth_headers):
    """改挂到另一家公司后，公司和归属个人一起变。"""
    first = create_personal(client, auth_headers, f"{TAG}-跳槽甲")["id"]
    second = create_personal(client, auth_headers, f"{TAG}-跳槽乙")["id"]
    work_a = create_work(client, auth_headers, first, f"{TAG}甲公司")
    work_b = create_work(client, auth_headers, second, f"{TAG}乙公司")

    project = client.post(
        PROJECTS,
        headers=auth_headers,
        json={"work_id": work_a["id"], "name": f"{TAG}跨公司项目"},
    ).json()
    assert project["company"] == f"{TAG}甲公司"

    moved = client.put(
        f"{PROJECTS}/{project['id']}", headers=auth_headers, json={"work_id": work_b["id"]}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["company"] == f"{TAG}乙公司"
    assert moved.json()["personal_info_id"] == second
    assert moved.json()["owner_name"] == f"{TAG}-跳槽乙"

    client.delete(f"{PERSONAL}/{first}", headers=auth_headers)
    client.delete(f"{PERSONAL}/{second}", headers=auth_headers)


def test_project_month_format(client, auth_headers):
    """项目起止时间同样只接受 YYYY-MM。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-项目月格式")["id"]
    work = create_work(client, auth_headers, person_id, f"{TAG}月格式公司")

    bad = client.post(
        PROJECTS,
        headers=auth_headers,
        json={"work_id": work["id"], "name": "某项目", "start_month": "2020年3月"},
    )
    assert bad.status_code == 422
    assert "YYYY-MM" in bad.text

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


# ==================== 自我评价 ====================
def test_evaluation_crud(client, auth_headers):
    person_id = create_personal(client, auth_headers, f"{TAG}-评价张三")["id"]

    payload = {
        "personal_info_id": person_id,
        "title": "个人优势",
        "content": "五年后端经验，熟悉 FastAPI 与 SQLAlchemy。",
        "sort": 4,
    }
    created = client.post(EVALUATIONS, headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    data = created.json()
    evaluation_id = data["id"]
    assert data["name"] == f"{TAG}-评价张三"

    listed = client.get(EVALUATIONS, headers=auth_headers, params={"keyword": TAG})
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["title"] == "个人优势"

    updated = client.put(
        f"{EVALUATIONS}/{evaluation_id}",
        headers=auth_headers,
        json={"content": "六年后端经验。"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "六年后端经验。"

    assert client.delete(f"{EVALUATIONS}/{evaluation_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{EVALUATIONS}/{evaluation_id}", headers=auth_headers).status_code == 404
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_evaluation_content_required(client, auth_headers):
    """评价内容必填。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-空评价")["id"]
    response = client.post(
        EVALUATIONS, headers=auth_headers, json={"personal_info_id": person_id, "content": ""}
    )
    assert response.status_code == 422
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


# ==================== 分级筛选 / 排序 / 分页 ====================
def test_bindings_are_isolated(client, auth_headers):
    """同一张表里的数据按归属个人互不串门。"""
    alice = create_personal(client, auth_headers, f"{TAG}-隔离甲")["id"]
    bob = create_personal(client, auth_headers, f"{TAG}-隔离乙")["id"]
    work_alice = create_work(client, auth_headers, alice, f"{TAG}隔离甲司")
    work_bob = create_work(client, auth_headers, bob, f"{TAG}隔离乙司")

    client.post(
        PROJECTS, headers=auth_headers, json={"work_id": work_alice["id"], "name": "甲的项目"}
    )
    client.post(
        PROJECTS, headers=auth_headers, json={"work_id": work_bob["id"], "name": "乙的项目"}
    )

    body = client.get(
        PROJECTS, headers=auth_headers, params={"personal_info_id": alice}
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "甲的项目"

    assert (
        client.get(WORKS, headers=auth_headers, params={"personal_info_id": bob}).json()["total"]
        == 1
    )

    client.delete(f"{PERSONAL}/{alice}", headers=auth_headers)
    client.delete(f"{PERSONAL}/{bob}", headers=auth_headers)


def test_sort_and_pagination(client, auth_headers):
    """列表按 sort 升序；分页字段齐全。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-排序")["id"]
    ids = []
    for sort in (30, 10, 20):
        response = client.post(
            WORKS,
            headers=auth_headers,
            json={
                "personal_info_id": person_id,
                "company": f"{TAG}公司-{sort}",
                "sort": sort,
            },
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])

    body = client.get(
        WORKS, headers=auth_headers, params={"keyword": TAG + "公司", "page": 1, "page_size": 2}
    ).json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert body["page_size"] == 2
    assert [item["sort"] for item in body["items"]] == [10, 20]

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


# ==================== 级联删除 ====================
def test_delete_work_removes_its_projects(client, auth_headers):
    """删公司经历时，挂在它下面的项目经历一起走。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-级联公司")["id"]
    work = create_work(client, auth_headers, person_id, f"{TAG}级联公司")
    project = client.post(
        PROJECTS, headers=auth_headers, json={"work_id": work["id"], "name": f"{TAG}级联项目"}
    ).json()

    assert client.delete(f"{WORKS}/{work['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"{PROJECTS}/{project['id']}", headers=auth_headers).status_code == 404
    # 人还在
    assert client.get(f"{PERSONAL}/{person_id}", headers=auth_headers).status_code == 200

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_delete_personal_removes_all_children(client, auth_headers):
    """删个人信息时，教育 / 工作 / 项目 / 自我评价全部级联删除。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-级联个人")["id"]
    education = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "school": f"{TAG}级联大学"},
    ).json()
    work = create_work(client, auth_headers, person_id, f"{TAG}级联公司")
    project = client.post(
        PROJECTS, headers=auth_headers, json={"work_id": work["id"], "name": f"{TAG}级联项目"}
    ).json()
    evaluation = client.post(
        EVALUATIONS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "content": f"{TAG}级联评价"},
    ).json()
    skill_tag = client.post(
        SKILLS,
        headers=auth_headers,
        json={
            "personal_info_id": person_id,
            "category": f"{TAG}级联分类",
            "tags": "pytest;Allure",
        },
    ).json()

    assert client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers).status_code == 200

    for url, item_id in (
        (EDUCATIONS, education["id"]),
        (WORKS, work["id"]),
        (PROJECTS, project["id"]),
        (EVALUATIONS, evaluation["id"]),
        (SKILLS, skill_tag["id"]),
    ):
        assert client.get(f"{url}/{item_id}", headers=auth_headers).status_code == 404, url


# ==================== 技能标签 ====================
def test_skill_tag_crud(client, auth_headers):
    """技能标签：分类 + 一个输入框里分号分隔的多个标签，落库会规整成标准格式。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-技能")["id"]

    created = client.post(
        SKILLS,
        headers=auth_headers,
        json={
            "personal_info_id": person_id,
            "category": " 测试与自动化 ",
            "tags": "Python； pytest ; Playwright;Python",
            "sort": 1,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["category"] == "测试与自动化"  # 分类去首尾空格
    assert item["tags"] == "Python;pytest;Playwright"  # 中英文分号都认，重复项去掉
    assert item["tag_list"] == ["Python", "pytest", "Playwright"]
    assert item["name"] == f"{TAG}-技能"  # 姓名随所属个人同步
    assert item["is_active"] is True

    listed = client.get(
        SKILLS, headers=auth_headers, params={"personal_info_id": person_id}
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == item["id"]

    # 按分类筛选能命中，换个分类名就查不到
    hit = client.get(SKILLS, headers=auth_headers, params={"category": "测试与自动化"})
    assert hit.json()["total"] == 1
    miss = client.get(SKILLS, headers=auth_headers, params={"category": "不存在的分类"})
    assert miss.json()["total"] == 0

    updated = client.put(
        f"{SKILLS}/{item['id']}", headers=auth_headers, json={"tags": "JMeter; SQL"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tag_list"] == ["JMeter", "SQL"]

    disabled = client.patch(
        f"{SKILLS}/{item['id']}/status", headers=auth_headers, json={"is_active": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    assert client.delete(f"{SKILLS}/{item['id']}", headers=auth_headers).status_code == 200
    assert client.get(f"{SKILLS}/{item['id']}", headers=auth_headers).status_code == 404

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_skill_tag_requires_existing_personal(client, auth_headers):
    """绑定不存在的个人信息 -> 404。"""
    response = client.post(
        SKILLS,
        headers=auth_headers,
        json={"personal_info_id": 999999, "category": "测试", "tags": "pytest"},
    )
    assert response.status_code == 404
    assert "个人信息不存在" in response.text


def test_skill_tag_rejects_empty_tags(client, auth_headers):
    """只填空格 / 分号视为没填，直接 422。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-空标签")["id"]
    response = client.post(
        SKILLS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "category": "测试", "tags": " ; ； "},
    )
    assert response.status_code == 422
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_skill_tag_rename_syncs_name(client, auth_headers):
    """改个人姓名后，技能标签里冗余的姓名跟着变。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-技能旧名")["id"]
    item = client.post(
        SKILLS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "category": "语言", "tags": "Python"},
    ).json()

    client.put(
        f"{PERSONAL}/{person_id}", headers=auth_headers, json={"name": f"{TAG}-技能新名"}
    )
    detail = client.get(f"{SKILLS}/{item['id']}", headers=auth_headers).json()
    assert detail["name"] == f"{TAG}-技能新名"

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


# ==================== 是否启用 ====================
def test_status_defaults_to_enabled(client, auth_headers):
    """新增时不传 is_active 默认启用；显式传 False 可以直接建为停用。"""
    enabled = create_personal(client, auth_headers, f"{TAG}-默认启用")
    assert enabled["is_active"] is True

    disabled = create_personal(
        client, auth_headers, f"{TAG}-默认停用", is_active=False
    )
    assert disabled["is_active"] is False

    client.delete(f"{PERSONAL}/{enabled['id']}", headers=auth_headers)
    client.delete(f"{PERSONAL}/{disabled['id']}", headers=auth_headers)


def test_status_toggle_and_filter(client, auth_headers):
    """五个类目都能启停，且列表能按启用状态过滤。"""
    person_id = create_personal(client, auth_headers, f"{TAG}-启停")["id"]
    work = create_work(client, auth_headers, person_id, f"{TAG}启停公司")
    education = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "school": f"{TAG}启停大学"},
    ).json()
    project = client.post(
        PROJECTS,
        headers=auth_headers,
        json={"work_id": work["id"], "name": f"{TAG}启停项目"},
    ).json()
    evaluation = client.post(
        EVALUATIONS,
        headers=auth_headers,
        json={"personal_info_id": person_id, "content": f"{TAG}启停评价"},
    ).json()

    cases = (
        (PERSONAL, person_id),
        (EDUCATIONS, education["id"]),
        (WORKS, work["id"]),
        (PROJECTS, project["id"]),
        (EVALUATIONS, evaluation["id"]),
    )

    # 新建的默认都是启用
    for url, item_id in cases:
        assert client.get(f"{url}/{item_id}", headers=auth_headers).json()["is_active"] is True

    # 逐个停用
    for url, item_id in cases:
        response = client.patch(
            f"{url}/{item_id}/status", headers=auth_headers, json={"is_active": False}
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is False

    # 列表过滤：停用的查得到，启用的查不到
    assert (
        client.get(PERSONAL, headers=auth_headers, params={"is_active": "false"}).json()["total"]
        == 1
    )
    assert (
        client.get(PERSONAL, headers=auth_headers, params={"is_active": "true"}).json()["total"]
        == 0
    )
    assert (
        client.get(WORKS, headers=auth_headers, params={"is_active": "false"}).json()["total"] == 1
    )
    assert (
        client.get(PROJECTS, headers=auth_headers, params={"is_active": "true"}).json()["total"]
        == 0
    )
    assert (
        client.get(
            EDUCATIONS, headers=auth_headers, params={"personal_info_id": person_id, "is_active": "false"}
        ).json()["total"]
        == 1
    )

    # 再启用回来
    for url, item_id in cases:
        response = client.patch(
            f"{url}/{item_id}/status", headers=auth_headers, json={"is_active": True}
        )
        assert response.json()["is_active"] is True

    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


def test_status_requires_token_and_existing(client, auth_headers):
    """启停接口同样要鉴权；对象不存在 404；is_active 必填。"""
    assert (
        client.patch(f"{PERSONAL}/1/status", json={"is_active": False}).status_code == 401
    )

    missing = client.patch(
        f"{PERSONAL}/999999/status", headers=auth_headers, json={"is_active": False}
    )
    assert missing.status_code == 404
    assert "个人信息不存在" in missing.text

    for url in (EDUCATIONS, WORKS, PROJECTS, EVALUATIONS, SKILLS):
        assert client.patch(f"{url}/999999/status", json={"is_active": True}).status_code == 401
        assert (
            client.patch(
                f"{url}/999999/status", headers=auth_headers, json={"is_active": True}
            ).status_code
            == 404
        )

    assert (
        client.patch(f"{PERSONAL}/1/status", headers=auth_headers, json={}).status_code == 422
    )


# ==================== OpenAPI 类目 ====================
def test_openapi_category(client):
    """六组接口自成类目：路径都收在 /resume 前缀下，且各有自己的 tag。"""
    schema = client.get("/api/v1/openapi.json").json()
    # `/resume/public/*` 是对外接口（另见 tests/test_resume_public.py），不算管理端类目
    resume_paths = [
        path
        for path in schema["paths"]
        if path.startswith("/api/v1/resume/") and not path.startswith("/api/v1/resume/public")
    ]
    # 六个类目 × (集合路径 + 详情路径 + 启停路径)
    # —— openapi 会把同一路径的不同方法合并成一条
    assert sorted(resume_paths) == [
        "/api/v1/resume/educations",
        "/api/v1/resume/educations/{education_id}",
        "/api/v1/resume/educations/{education_id}/status",
        "/api/v1/resume/evaluations",
        "/api/v1/resume/evaluations/{evaluation_id}",
        "/api/v1/resume/evaluations/{evaluation_id}/status",
        "/api/v1/resume/personal-infos",
        "/api/v1/resume/personal-infos/upload-avatar",
        "/api/v1/resume/personal-infos/{info_id}",
        "/api/v1/resume/personal-infos/{info_id}/status",
        "/api/v1/resume/projects",
        "/api/v1/resume/projects/{project_id}",
        "/api/v1/resume/projects/{project_id}/status",
        "/api/v1/resume/skill-tags",
        "/api/v1/resume/skill-tags/{skill_tag_id}",
        "/api/v1/resume/skill-tags/{skill_tag_id}/status",
        "/api/v1/resume/work-experiences",
        "/api/v1/resume/work-experiences/{work_id}",
        "/api/v1/resume/work-experiences/{work_id}/status",
    ]

    tags = {
        tag
        for path in resume_paths
        for method in schema["paths"][path].values()
        for tag in method.get("tags", [])
    }
    assert tags == {
        "后台-个人网站-个人信息",
        "后台-个人网站-教育信息",
        "后台-个人网站-工作经历",
        "后台-个人网站-项目经历",
        "后台-个人网站-自我评价",
        "后台-个人网站-技能标签",
    }

    # 六组的形状一致：集合路径上只有列表与新增，详情路径上只有查询 / 更新 / 删除，
    # 启停路径上只有 PATCH
    status_paths = {
        "personal-infos": "info_id",
        "educations": "education_id",
        "work-experiences": "work_id",
        "projects": "project_id",
        "evaluations": "evaluation_id",
        "skill-tags": "skill_tag_id",
    }
    for path in (
        "personal-infos",
        "educations",
        "work-experiences",
        "projects",
        "evaluations",
        "skill-tags",
    ):
        assert set(schema["paths"][f"/api/v1/resume/{path}"]) == {"get", "post"}, path
        assert set(schema["paths"][f"/api/v1/resume/{path}/{{{status_paths[path]}}}"]) == {
            "get",
            "put",
            "delete",
        }, path
        assert set(schema["paths"][f"/api/v1/resume/{path}/{{{status_paths[path]}}}/status"]) == {
            "patch"
        }, path
