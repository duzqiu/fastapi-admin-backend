"""个人简历对外接口测试（`/resume/public/profiles` 这一个合并接口）。

这组接口是给前台展示端用的，验收点五条：

1. **不需要登录** —— 不带任何令牌也能拿到数据；
2. **一次拿全** —— 个人信息 + 教育 + 工作（含其下项目）+ 自我评价，结构固定；
3. **两种用法** —— 传 `personal_info_id` 只取一个人；不传取所有启用中的人；
4. **只出启用数据** —— 自己停用、或父级停用，都不该再出现；
5. **和管理端互不影响** —— 路径、tag 独立，管理端该 401 还是 401。
"""

API = "/api/v1"
PUBLIC = f"{API}/resume/public"

# 管理端（用来造数据 / 做对照）
PERSONAL = f"{API}/resume/personal-infos"
EDUCATIONS = f"{API}/resume/educations"
WORKS = f"{API}/resume/work-experiences"
PROJECTS = f"{API}/resume/projects"
EVALUATIONS = f"{API}/resume/evaluations"
SKILLS = f"{API}/resume/skill-tags"

TAG = "对外接口测试"


# ==================== 工具 ====================
def create_tree(client, auth_headers, suffix=""):
    """建一棵完整的小简历树：个人 -> 教育 / 工作(-> 项目) / 自我评价。"""
    person = client.post(
        PERSONAL,
        headers=auth_headers,
        json={
            "name": f"{TAG}-{suffix}",
            "phone": "13600000000",
            "email": "public@example.com",
            "city": "杭州",
            "job_intention": "后端工程师",
        },
    ).json()
    work = client.post(
        WORKS,
        headers=auth_headers,
        json={
            "personal_info_id": person["id"],
            "company": f"{TAG}公司{suffix}",
            "position": "架构师",
            "department": "平台部",
            "start_month": "2019-06",
        },
    ).json()
    education = client.post(
        EDUCATIONS,
        headers=auth_headers,
        json={
            "personal_info_id": person["id"],
            "school": f"{TAG}大学{suffix}",
            "major": "软件工程",
            "degree": "bachelor",
            "start_month": "2012-09",
            "end_month": "2016-06",
        },
    ).json()
    project = client.post(
        PROJECTS,
        headers=auth_headers,
        json={
            "work_id": work["id"],
            "name": f"{TAG}项目{suffix}",
            "role": "后端负责人",
            "start_month": "2020-01",
            "duty": "负责接口自动化框架搭建",
            "achievement": "回归耗时从两天降到 40 分钟",
        },
    ).json()
    evaluation = client.post(
        EVALUATIONS,
        headers=auth_headers,
        json={
            "personal_info_id": person["id"],
            "title": "个人优势",
            "content": f"{TAG}评价内容{suffix}",
        },
    ).json()
    skill_tag = client.post(
        SKILLS,
        headers=auth_headers,
        json={
            "personal_info_id": person["id"],
            "category": "测试与自动化",
            "tags": "pytest;Playwright",
        },
    ).json()
    return {
        "person": person,
        "work": work,
        "education": education,
        "project": project,
        "evaluation": evaluation,
        "skill_tag": skill_tag,
    }


def fetch_profiles(client, **params):
    """调对外接口（不带任何令牌）。"""
    response = client.get(f"{PUBLIC}/profiles", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def fetch_one(client, person_id):
    """按个人 ID 取整份简历。"""
    profiles = fetch_profiles(client, personal_info_id=person_id)
    assert len(profiles) == 1
    return profiles[0]


def drop_tree(client, auth_headers, person_id):
    """删掉个人信息，级联清干净（测试收尾用）。"""
    client.delete(f"{PERSONAL}/{person_id}", headers=auth_headers)


# ==================== 1. 无需登录 / 合并成一个接口 ====================
def test_public_profiles_need_no_token(client):
    """不带任何凭证就能访问，且返回的是数组。"""
    response = client.get(f"{PUBLIC}/profiles")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_resume_still_requires_token(client):
    """管理端那套仍然要鉴权，没有因为新增公开接口被放开。"""
    for url in (PERSONAL, EDUCATIONS, WORKS, PROJECTS, EVALUATIONS):
        assert client.get(url).status_code == 401, url


def test_public_openapi_is_separate(client):
    """对外只暴露一个接口，自成一类目，且不带鉴权声明。"""
    schema = client.get("/api/v1/openapi.json").json()
    public_paths = [path for path in schema["paths"] if path.startswith(PUBLIC)]
    assert public_paths == [f"{PUBLIC}/profiles"]

    methods = schema["paths"][f"{PUBLIC}/profiles"]
    assert set(methods) == {"get"}
    assert methods["get"]["tags"] == ["前端-个人网站"]
    assert not methods["get"].get("security")

    # 管理端同类接口依然要求鉴权，两边互不影响
    admin_get = schema["paths"][f"{API}/resume/personal-infos"]["get"]
    assert admin_get["tags"] == ["后台-个人网站-个人信息"]


# ==================== 2. 传 ID：取指定用户的全部信息 ====================
def test_public_profiles_for_one_person(client, auth_headers):
    """传 personal_info_id 时，返回这个人完整的五块信息，且项目挂在公司下面。"""
    tree = create_tree(client, auth_headers, "单人")
    person_id = tree["person"]["id"]

    profile = fetch_one(client, person_id)

    # 个人信息
    assert profile["personal_info"]["id"] == person_id
    assert profile["personal_info"]["name"] == f"{TAG}-单人"
    assert profile["personal_info"]["city"] == "杭州"
    assert profile["personal_info"]["avatar"] == ""
    # 对外出参不含内部字段
    assert "is_active" not in profile["personal_info"]
    assert "created_at" not in profile["personal_info"]

    # 教育经历
    assert len(profile["educations"]) == 1
    assert profile["educations"][0]["school"] == f"{TAG}大学单人"
    assert profile["educations"][0]["degree_text"] == "本科"

    # 工作经历（公司），项目嵌在它下面 —— 所以不用再回显「属于哪家公司」
    assert len(profile["work_experiences"]) == 1
    work = profile["work_experiences"][0]
    assert work["company"] == f"{TAG}公司单人"
    assert work["position"] == "架构师"
    assert len(work["projects"]) == 1
    assert work["projects"][0]["name"] == f"{TAG}项目单人"
    assert work["projects"][0]["role"] == "后端负责人"
    # 项目职责 / 业绩单独透出，前台按块展示
    assert work["projects"][0]["duty"] == "负责接口自动化框架搭建"
    assert work["projects"][0]["achievement"] == "回归耗时从两天降到 40 分钟"
    assert "work" not in work["projects"][0]

    # 自我评价
    assert len(profile["evaluations"]) == 1
    assert profile["evaluations"][0]["content"] == f"{TAG}评价内容单人"

    # 技能标签：分类 + 已经拆好的标签数组
    assert len(profile["skill_tags"]) == 1
    assert profile["skill_tags"][0]["category"] == "测试与自动化"
    assert profile["skill_tags"][0]["tags"] == ["pytest", "Playwright"]

    drop_tree(client, auth_headers, person_id)


def test_public_profile_carries_avatar(client, auth_headers):
    """头像会一起带给前台（上传链路由 tests/test_resume.py 覆盖，这里只看字段透传）。"""
    tree = create_tree(client, auth_headers, "头像")
    person_id = tree["person"]["id"]
    avatar = "https://cdn.example.com/a.png"

    client.put(f"{PERSONAL}/{person_id}", headers=auth_headers, json={"avatar": avatar})

    assert fetch_one(client, person_id)["personal_info"]["avatar"] == avatar

    drop_tree(client, auth_headers, person_id)


def test_public_profiles_unknown_person_404(client):
    """不存在的主键返回 404（不泄露「存在但停用」这个差异）。"""
    assert client.get(f"{PUBLIC}/profiles", params={"personal_info_id": 999999}).status_code == 404


# ==================== 3. 不传 ID：取所有用户 ====================
def test_public_profiles_all_persons(client, auth_headers):
    """不传 personal_info_id 时，所有启用中的人都在结果里，且各自带着自己的数据。"""
    first = create_tree(client, auth_headers, "批量甲")
    second = create_tree(client, auth_headers, "批量乙")
    ids = [first["person"]["id"], second["person"]["id"]]

    profiles = fetch_profiles(client)
    by_person = {item["personal_info"]["id"]: item for item in profiles}
    assert set(ids) <= set(by_person)

    # 各人的数据不会串门
    assert by_person[ids[0]]["educations"][0]["school"] == f"{TAG}大学批量甲"
    assert by_person[ids[1]]["work_experiences"][0]["company"] == f"{TAG}公司批量乙"
    assert by_person[ids[0]]["work_experiences"][0]["projects"][0]["name"] == f"{TAG}项目批量甲"

    # limit 只收敛返回的人数
    assert len(fetch_profiles(client, limit=1)) == 1

    for person_id in ids:
        drop_tree(client, auth_headers, person_id)


# ==================== 4. 只出启用数据 ====================
def test_public_hides_disabled_record(client, auth_headers):
    """自己停用的条目，对外立刻看不到；管理端照常可见。"""
    tree = create_tree(client, auth_headers, "条目停用")
    person_id = tree["person"]["id"]
    education_id = tree["education"]["id"]

    assert len(fetch_one(client, person_id)["educations"]) == 1

    client.patch(
        f"{EDUCATIONS}/{education_id}/status", headers=auth_headers, json={"is_active": False}
    )
    assert fetch_one(client, person_id)["educations"] == []
    # 管理端还在
    assert client.get(f"{EDUCATIONS}/{education_id}", headers=auth_headers).status_code == 200

    drop_tree(client, auth_headers, person_id)


def test_public_hides_children_of_disabled_parent(client, auth_headers):
    """个人信息停用后：按 ID 查 404，不传 ID 时这个人整个不出现。"""
    tree = create_tree(client, auth_headers, "个人停用")
    person_id = tree["person"]["id"]

    client.patch(
        f"{PERSONAL}/{person_id}/status", headers=auth_headers, json={"is_active": False}
    )

    assert (
        client.get(f"{PUBLIC}/profiles", params={"personal_info_id": person_id}).status_code == 404
    )
    all_ids = [item["personal_info"]["id"] for item in fetch_profiles(client)]
    assert person_id not in all_ids

    drop_tree(client, auth_headers, person_id)


def test_public_hides_disabled_work_with_its_projects(client, auth_headers):
    """公司经历停用后：这段经历连同它名下的项目一起不再输出。"""
    tree = create_tree(client, auth_headers, "公司停用")
    person_id = tree["person"]["id"]
    work_id = tree["work"]["id"]
    project_id = tree["project"]["id"]

    assert len(fetch_one(client, person_id)["work_experiences"]) == 1

    client.patch(f"{WORKS}/{work_id}/status", headers=auth_headers, json={"is_active": False})

    profile = fetch_one(client, person_id)
    assert profile["work_experiences"] == []
    # 个人信息 / 教育 / 评价不受影响
    assert profile["educations"]
    assert profile["evaluations"]
    # 公司经历和项目本身都没被删，管理端照常可见
    assert client.get(f"{WORKS}/{work_id}", headers=auth_headers).status_code == 200
    assert client.get(f"{PROJECTS}/{project_id}", headers=auth_headers).status_code == 200

    drop_tree(client, auth_headers, person_id)
