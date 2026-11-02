# 后台管理系统 · FastAPI 后端

基于 **FastAPI + SQLAlchemy 2.0 + Pydantic V2** 的分层接口服务。本地零配置使用 SQLite，
可通过脚本迁移到 PostgreSQL / MySQL；同时为三个客户端提供 API：

| 客户端 | 身份 | 说明 |
| --- | --- | --- |
| `fastapi-admin-frontend` | 后台账号（`scope=staff`） | Vue 3 后台管理界面 |
| `flet-post-app` | 会员（`scope=member`） | Flet 跨平台移动端 App |
| 个人网站前台 | 匿名 | 简历公开接口 + 站点欢迎语 |

系统显示名称由 `PROJECT_NAME` 统一控制（默认 `后台管理系统`），同步出现在接口文档标题、
根路径响应、后台「系统信息」卡片与邮件标题中。

---

## 目录

- [一、项目简介](#一项目简介)
- [二、技术栈](#二技术栈)
- [三、分层架构设计](#三分层架构设计)
- [四、目录结构](#四目录结构)
- [五、快速开始](#五快速开始)
- [六、环境变量说明](#六环境变量说明)
- [七、接口清单](#七接口清单)
- [八、账号体系与认证](#八账号体系与认证)
- [九、内容体系（动态 / 官号文章 / 互动 / 消息）](#九内容体系动态--官号文章--互动--消息)
- [十、个人网站（简历 + 站点设置）](#十个人网站简历--站点设置)
- [十一、数据库与结构演进](#十一数据库与结构演进)
- [十二、测试](#十二测试)
- [十三、生产部署](#十三生产部署)
- [十四、与客户端项目的对接](#十四与客户端项目的对接)

---

## 一、项目简介

| 能力 | 说明 |
| --- | --- |
| 双账号体系 | 后台账号（管理员创建、带角色）与会员（邮箱自助注册），JWT 按 `scope` 隔离 |
| 内容 | 用户动态（发布 / 审核 / 点赞 / 收藏 / 评论）、官号文章（独立域，与动态同流展示） |
| 社交 | 关注（关注流 / 关注列表）、站内消息（评论 / 点赞 / 审核结果 / 公告）、未读数 |
| 个人网站 | 六组简历数据（个人信息 / 教育 / 工作 / 项目 / 评价 / 技能标签）+ 对外合并接口 |
| 站点设置 | 首页欢迎语三件套、「关于我」访问密码（bcrypt） |
| 媒体 | 头像 / 背景图 / 动态图 / 简历头像上传，魔术字节校验、长边压缩、HEIC 自动转 JPEG |
| 基础设施 | 统一配置、统一异常与错误码、统一分页、请求日志（`X-Request-Id`）、CORS、SMTP、Alembic |
| 结构自愈 | 启动时自动建表、补列、放宽列长度；下线功能遗留表按白名单清理 |

分层原则：**接口层只收参**、**服务层管业务与事务**、**仓储层管数据**，
横切能力（配置 / 安全 / 日志 / 异常 / 存储）集中在 `app/core`。

---

## 二、技术栈

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| Python | ≥ 3.10（已在 3.13 验证） | 运行环境 |
| FastAPI | 0.115.6 | Web 框架 / OpenAPI 文档 |
| Uvicorn | 0.34.0 | ASGI 服务器 |
| SQLAlchemy | ≥ 2.0.44 | ORM（2.0 声明式 `Mapped` / `mapped_column`） |
| Pydantic / pydantic-settings | ≥ 2.10.4 / ≥ 2.7.0 | 校验与配置 |
| Alembic | 1.14.0 | 结构版本管理 |
| PyJWT + bcrypt | 2.10.1 / 4.2.1 | 令牌签发与密码哈希（刻意不用 passlib，规避 Python 3.13 `crypt` 移除） |
| pillow / pillow-heif | ≥ 10.3 / ≥ 0.18 | 图片处理与 HEIC 解码 |
| psycopg[binary] / PyMySQL | ≥ 3.2.3 / 1.1.1 | PG / MySQL 驱动（按需） |
| lunar-python | 1.4.8 | 公历 ↔ 农历换算 |
| pytest + httpx | 8.3.4 / 0.28.1 | 测试 |

依赖清单见 `requirements.txt`（项目未使用 `pyproject.toml`）。

---

## 三、分层架构设计

```
HTTP 请求
   │
   ▼
┌──────────────────────────────────────────────────────────────┐
│ 中间件  CORS、RequestLogMiddleware（X-Request-Id / 耗时）      │
├──────────────────────────────────────────────────────────────┤
│ 接口层 API       路由、Pydantic 校验、鉴权依赖、分页参数        │
│  app/api/**        只做「收参 → 调服务 → 返回」                │
├──────────────────────────────────────────────────────────────┤
│ 服务层 Services  业务规则、组合仓储、事务边界（commit）         │
│  app/services/**   抛语义化异常，不关心 HTTP                   │
├──────────────────────────────────────────────────────────────┤
│ 仓储层 Repositories  纯数据访问，只 flush 不 commit            │
│  app/repositories/** 唯一允许出现 SQLAlchemy 查询的地方        │
├──────────────────────────────────────────────────────────────┤
│ 模型层 Models    ORM 表结构（app/models/**）                  │
└──────────────────────────────────────────────────────────────┘
   ▲ 横切关注点：core/（配置/安全/日志/异常/存储/邮件/农历）、schemas/、db/
```

**关键约束**

1. 接口层不写 SQL、不写业务规则。
2. 服务层不直接 `select()`，数据访问一律走仓储层。
3. 仓储层只 `flush`，事务提交由服务层控制，支持多步操作原子提交。
4. 服务层抛 `NotFoundError` / `ConflictError` / `BusinessError`（`app/core/exceptions.py`），
   由全局处理器翻译为统一错误码响应。
5. 依赖注入集中在 `app/api/deps.py`，测试可用 `app.dependency_overrides` 替换。

---

## 四、目录结构

```
fastapi-admin-backend/
├── app/
│   ├── main.py                      应用入口：CORS / 日志中间件 / 异常 / 路由 / 静态资源 / lifespan
│   │
│   ├── core/                        ★ 横切关注点
│   │   ├── config.py                全局配置（pydantic-settings，缓存单例）
│   │   ├── security.py              bcrypt 哈希、JWT 签发/解析、staff / member 作用域
│   │   ├── exceptions.py            业务异常 + 全局异常处理器 + 错误码
│   │   ├── mailer.py                SMTP 发信（未启用时只打日志）、验证码邮件模板
│   │   ├── storage.py               通用图片上传：后缀/大小/魔术字节/长边压缩/HEIC 转 JPEG
│   │   ├── member_media.py          会员头像与背景图地址解析（按会员 ID 反查磁盘文件）
│   │   ├── site_password.py         站点「关于我」密码哈希（SHA-256 预处理 + bcrypt）
│   │   ├── lunar.py                 农历文本、节气 / 节日
│   │   ├── logging.py               日志格式与初始化
│   │   └── utils.py                 UTC 时间、本地时间、10 位会员编号生成
│   │
│   ├── db/
│   │   ├── base.py                  DeclarativeBase
│   │   ├── session.py               引擎（自动适配 SQLite/PG/MySQL）、SessionLocal、get_db
│   │   ├── init_db.py               建表 + 删遗留表 + 补列 + 初始管理员/演示会员/站点设置（幂等）
│   │   ├── schema_sync.py           自动补列、自动放宽字符串长度（只加/只放宽）
│   │   └── legacy_cleanup.py        按白名单删除下线功能遗留表（8 张）
│   │
│   ├── models/                      ★ ORM（表名规范：一级_二级_功能）
│   │   ├── mixins.py                PKMixin / TimestampMixin
│   │   ├── user.py                  system_auth_admin_user + UserRole
│   │   ├── member.py                member_account_info / member_account_follow + MemberGender
│   │   ├── email_code.py            member_account_email_code + EmailScene
│   │   ├── post.py                  article_post_info / _like / _favorite / _comment
│   │   ├── official_article.py      article_official_info / _like / _favorite / _comment + ARTICLE_ID_OFFSET
│   │   ├── message.py               member_account_message + MessageType
│   │   ├── resume.py                resume_base_personal_info / _education / _work / _project / _evaluation / _skill_tag
│   │   ├── site_setting.py          site_setting（单例 id=1）
│   │   └── __init__.py              统一导出（新增模型必须在此注册）
│   │
│   ├── schemas/                     ★ DTO（auth / user / member / email / post / official_article /
│   │                                  message / resume / resume_public / site / system / common）
│   │
│   ├── repositories/                ★ 数据访问
│   │   ├── base.py                  通用 CRUD / 分页 / 统计
│   │   ├── user_repository.py
│   │   ├── member_repository.py     会员 + MemberFollowRepository
│   │   ├── email_code_repository.py
│   │   ├── post_repository.py       动态 / 评论 / 点赞 / 收藏
│   │   ├── official_article_repository.py
│   │   ├── official_article_interaction_repository.py   点赞 / 收藏
│   │   ├── official_article_comment_repository.py
│   │   ├── message_repository.py
│   │   ├── resume_repository.py     六类简历数据
│   │   └── site_repository.py
│   │
│   ├── services/                    ★ 业务逻辑
│   │   ├── auth_service.py          后台登录 / 刷新 / 改密
│   │   ├── user_service.py          后台账号 CRUD + 最后管理员保护
│   │   ├── email_code_service.py    验证码生成、限流、发送、校验
│   │   ├── member_auth_service.py   会员注册 / 登录 / 刷新 / 重置密码
│   │   ├── member_service.py        会员资料、媒体上传、后台管理、关注
│   │   ├── post_service.py          动态 / 评论 / 点赞 / 收藏 / 关注流（含官号文章合流）
│   │   ├── article_feed.py          官号文章 → 帖子出参映射、ID 偏移、列表合并与排序
│   │   ├── official_article_service.py  官号文章 CRUD / 审核 / 访问量
│   │   ├── message_service.py       站内消息、未读数、已读
│   │   ├── resume_service.py        六类简历 CRUD / 启停 / 对外合并
│   │   ├── site_service.py          欢迎语、关于我密码
│   │   └── system_service.py        健康检查 / 运行信息 / 首页统计
│   │
│   ├── api/
│   │   ├── deps.py                  Session、当前用户/会员、管理员校验、分页、各 Service
│   │   └── v1/
│   │       ├── router.py            v1 聚合
│   │       └── endpoints/           auth / users / member_auth / member_profile / member_public /
│   │                                members / posts / official_articles / messages / resume /
│   │                                resume_public / site / system
│   ├── middlewares/request_log.py   X-Request-Id、耗时、跳过文档与静态资源
│   └── static/                      内置资源（default-avatar.svg）
│
├── alembic/                         5 个版本（地区、背景图、收藏、官号文章、删除遗留表）
├── scripts/
│   ├── init_db.py                   手动初始化（等价于启动时的 init_db）
│   └── migrate_database.py          SQLite → PG/MySQL 数据迁移 / 行数校验
├── tests/                           22 个 pytest 文件（见第十二节）
├── data/                            SQLite 与上传目录（git 忽略，自动创建）
├── run.py                           开发启动脚本
├── requirements.txt / pytest.ini
├── Dockerfile / .dockerignore / docker-compose.yml / .env.docker.example
├── .env.example
└── README.md
```

---

## 五、快速开始

> 命令以 Windows PowerShell 为例；Linux/macOS 把 `.venv/Scripts/python` 换成 `.venv/bin/python`。

### 1. 安装依赖

```powershell
cd fastapi-admin-backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install --upgrade pip
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 2. 准备配置

```powershell
Copy-Item .env.example .env
```

至少确认 `SECRET_KEY`（生产必须改）与 `DATABASE_URL`（默认 SQLite，无需改）。

### 3. 初始化数据库（可跳过）

```powershell
./.venv/Scripts/python.exe scripts/init_db.py
```

应用启动时 `lifespan` 也会调用同一套 `init_db()`，幂等可重复执行。默认创建：

- 后台账号 `admin / admin123`
- 3 个演示会员（`alice@example.com` / `bob@example.com` / `carol@example.com`，密码统一 `members123`）
- 站点设置单例（「关于我」默认密码 `123456`）

### 4. 启动

```powershell
# 方式一：读取 .env 的 HOST/PORT，DEBUG=true 时自动热重载
./.venv/Scripts/python.exe run.py

# 方式二：直接 uvicorn
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

| 地址 | 说明 |
| --- | --- |
| http://127.0.0.1:8000/docs | Swagger UI（Authorize 可用 `admin/admin123`） |
| http://127.0.0.1:8000/redoc | ReDoc |
| http://127.0.0.1:8000/api/v1/openapi.json | OpenAPI 描述 |
| http://127.0.0.1:8000/api/v1/system/health | 健康检查 |

### 5. 验证

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"admin123\"}'
```

---

## 六、环境变量说明

### 基础与安全

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROJECT_NAME` | 后台管理系统 | 系统显示名称 |
| `VERSION` / `DESCRIPTION` | 1.0.0 / … | OpenAPI 信息 |
| `API_V1_PREFIX` | `/api/v1` | 接口前缀（同时决定静态资源挂载点） |
| `DEBUG` | true | 调试模式（影响热重载） |
| `HOST` / `PORT` | 0.0.0.0 / 8000 | 监听地址与端口 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `DATABASE_URL` | sqlite:///./data/app.db | 连接串 |
| `SQL_ECHO` | false | 是否打印 SQL |
| `DROP_LEGACY_TABLES` | true | 启动时删除下线功能的遗留表（8 张，不可恢复） |
| `SECRET_KEY` | 示例值 | JWT 签名密钥，**生产必须更换** |
| `ALGORITHM` | HS256 | JWT 算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | access_token 有效期 |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | 10080 | refresh_token 有效期 |
| `BACKEND_CORS_ORIGINS` | 5173 / 4173 本地地址 | 允许跨域来源，逗号分隔 |
| `FIRST_SUPERUSER_USERNAME/PASSWORD/EMAIL/NICKNAME` | admin / admin123 / … | 初始管理员 |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | 10 / 200 | 分页默认值与上限 |

### 邮件与验证码

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAIL_ENABLED` | false | false 时验证码只写日志 |
| `MAIL_HOST` / `MAIL_PORT` | smtp.example.com / 465 | SMTP 服务器 |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | 空 | 登录账号（多数邮箱用授权码） |
| `MAIL_FROM` | 后台管理系统 <noreply@example.com> | 发件人，建议与 `MAIL_USERNAME` 完全一致 |
| `MAIL_USE_SSL` | true | true = `SMTP_SSL`；false = `SMTP + STARTTLS` |
| `MAIL_TIMEOUT` | 10 | 发信超时（秒） |
| `EMAIL_CODE_LENGTH` | 6 | 验证码位数 |
| `EMAIL_CODE_EXPIRE_MINUTES` | 10 | 有效期 |
| `EMAIL_CODE_RESEND_SECONDS` | 60 | 同邮箱 + 场景冷却时间 |
| `EMAIL_CODE_MAX_ATTEMPTS` | 5 | 最多校验失败次数 |
| `EMAIL_CODE_DEBUG_RETURN` | true | 是否在响应回显 `debug_code`（**生产必须 false**） |

### 媒体

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEFAULT_AVATAR` | /api/v1/assets/default-avatar.svg | 默认头像 |
| `UPLOAD_DIR` | ./data/uploads | 上传目录（相对路径以项目根为基准） |
| `IMAGE_MAX_SIZE_MB` | 10 | 图片大小上限 |
| `IMAGE_SHRINK_MAX_SIDE` | 1600 | 落盘前长边压缩尺寸 |
| `IMAGE_ALLOWED_EXTENSIONS` | jpg,jpeg,png,webp,gif,heic,heif | HEIC/HEIF 落盘前转 JPEG |

生成随机密钥：

```powershell
./.venv/Scripts/python.exe -c "import secrets;print(secrets.token_urlsafe(48))"
```

### 在 Docker 里启用邮件

环境变量只在创建容器时注入，改完必须**重建**（`restart` 不会重读 `.env`）：

```bash
cd /opt/fastapi-admin
sed -i '/^MAIL_/d' .env
cat >> .env <<'EOF'
MAIL_ENABLED=true
MAIL_HOST=smtp.qq.com
MAIL_PORT=465
MAIL_USE_SSL=true
MAIL_USERNAME=你的QQ邮箱@qq.com
MAIL_PASSWORD=邮箱后台生成的SMTP授权码
MAIL_FROM=你的QQ邮箱@qq.com
EOF
docker compose up -d --force-recreate --no-build backend
docker exec admin-backend env | grep -i '^MAIL_'
```

验证发信能力：

```bash
docker exec admin-backend python -c "from app.core.mailer import send_mail, build_code_mail; s, h = build_code_mail('123456', 'register'); print('投递结果 =', send_mail('收件邮箱@example.com', s, h))"
```

---

## 七、接口清单

统一前缀 `/api/v1`，共 **135 个端点**。除标注「公开」外均需 `Authorization: Bearer <access_token>`。

> 权限三档：**公开**（匿名可访问）/ **登录**（任意有效令牌）/ **会员**（`scope=member`）/
> **管理员**（`scope=staff` 且 `role=admin`）。

### 后台认证 `/auth`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/auth/login` | JSON 登录，返回 access / refresh | 公开 |
| POST | `/auth/token` | OAuth2 表单登录（Swagger 用） | 公开 |
| POST | `/auth/refresh` | 刷新令牌 | 公开 |
| GET | `/auth/me` | 当前后台账号 | 登录 |
| POST | `/auth/change-password` | 修改自己的密码 | 登录 |
| POST | `/auth/logout` | 登出（前端清令牌即可） | 登录 |

### 后台账号 `/users`（管理员）

`GET /users`（分页 + `keyword` / `role` / `is_active`）、`POST /users`、`GET /users/{id}`、
`PUT /users/{id}`、`PATCH /users/{id}/status`、`PATCH /users/{id}/password`、`DELETE /users/{id}`。

> 内置保护：不能删除 / 禁用 / 降级「最后一个管理员」，不能禁用或删除当前登录账号。

### 会员认证 `/member/auth`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/member/auth/check-email` | 检查邮箱是否已注册 | 公开 |
| POST | `/member/auth/send-code` | 发送验证码（`scene=register` / `reset_password`） | 公开 |
| POST | `/member/auth/register` | 邮箱验证码注册（分配 10 位会员编号 + 默认昵称/头像） | 公开 |
| POST | `/member/auth/login` | 邮箱 + 密码登录 | 公开 |
| POST | `/member/auth/token` | OAuth2 表单登录（Swagger 用） | 公开 |
| POST | `/member/auth/refresh` | 刷新会员令牌 | 公开 |
| POST | `/member/auth/verify-register-code` | 仅校验注册验证码，不消耗验证码 | 公开 |
| POST | `/member/auth/verify-reset-code` | 仅校验重置密码验证码，不消耗验证码 | 公开 |
| POST | `/member/auth/reset-password` | 忘记密码（验证码重置） | 公开 |
| GET | `/member/auth/me` | 当前登录会员 | 会员 |
| POST | `/member/auth/logout` | 退出登录 | 会员 |

### 会员个人中心 `/member`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/member/profile` | 我的资料（含可直接用的 `avatar_url` / `background_url`） |
| PUT | `/member/profile` | 改昵称 / 头像 / 背景图 / 性别 / 生日 / 手机号 / 简介 / 地区 |
| POST | `/member/profile/avatar` | 上传头像（multipart，字段 `file`） |
| POST | `/member/profile/background` | 上传背景图 |
| POST | `/member/send-code` | 已登录时获取「修改密码」验证码（发到当前账号邮箱） |
| POST | `/member/profile/change-password` | 修改密码（`code` + `new_password` + `confirm_password`） |

### 会员公开资料与关注 `/members`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/members/{id}/public` | 公开资料（昵称 / 头像 / 简介 / 地区 / 会员编号），被禁用按 404 | 公开 |
| GET | `/members/me/following` | 我关注的人（分页） | 会员 |
| POST | `/members/{id}/follow` | 关注（幂等） | 会员 |
| DELETE | `/members/{id}/follow` | 取消关注（幂等） | 会员 |

### 会员管理（后台）`/members`（管理员）

`GET /members`（`keyword` 支持会员编号 / 邮箱 / 昵称 / 手机号，另有 `gender` / `is_active` /
`email_verified` / `registered_after` / `registered_before`）、`GET /members/stats`、
`GET /members/{id}`、`PUT /members/{id}`、`PATCH /members/{id}/status`、
`PATCH /members/{id}/password`、`DELETE /members/{id}`，以及媒体：
`POST/GET /members/{id}/avatar`、`POST/GET /members/{id}/background`。

### 动态与评论 `/posts` · `/comments`

**用户端（`public_router`，部分需会员令牌）**

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/posts` | 发动态（默认待审核） | 会员 |
| PATCH | `/posts/{id}` | 修改被拒绝的动态并重新提交 | 会员 |
| POST | `/posts/images` | 上传动态图片（multipart） | 会员 |
| GET | `/posts/latest` | 最新已通过动态 | 公开 |
| GET | `/posts/hot` | 热门（按访问量） | 公开 |
| GET | `/posts/recommend` | 推荐（近一年随机 10 条） | 公开 |
| GET | `/posts/recommend/page` | 推荐（分页） | 公开 |
| GET | `/posts/following` | 关注流 | 会员 |
| GET | `/posts/by-member/{member_id}` | 某会员的动态 | 公开 |
| GET | `/posts/detail/{id}` | 详情（仅已通过，App 消息跳转用） | 公开 |
| GET | `/posts/mine/{id}` | 我的一条动态（不限状态，改稿用） | 会员 |
| POST | `/posts/{id}/view` | 记录一次访问 | 公开 |
| POST/DELETE | `/posts/{id}/like` | 点赞 / 取消（幂等） | 会员 |
| POST/DELETE | `/posts/{id}/favorite` | 收藏 / 取消（幂等） | 会员 |
| GET | `/posts/favorites` | 我收藏的动态 | 会员 |
| GET | `/posts/received-likes` | 我的获赞总数 | 会员 |
| GET | `/posts/received-likes/posts` | 我获赞的动态列表 | 会员 |
| GET | `/posts/received-comments` | 我的被评论总数 | 会员 |
| GET | `/posts/commented-posts` | 我被评论的动态列表 | 会员 |
| POST | `/posts/{id}/comments` | 发表评论（默认待审核） | 会员 |
| GET | `/posts/{id}/comments` | 某动态下已通过评论 | 公开 |

**后台（管理员）**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/posts` | 动态列表（分页 + 筛选） |
| GET | `/posts/{id}` | 动态详情 |
| PATCH | `/posts/{id}/status` | 审核（`approved` / `rejected`，终态） |
| DELETE | `/posts/{id}` | 删除动态 |
| GET | `/comments` | 评论列表（分页 + 筛选） |
| PATCH | `/comments/{id}/status` | 审核评论 |
| DELETE | `/comments/{id}` | 删除评论 |

### 官号文章 `/official-articles`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/official-articles` | 列表（`keyword` / `status` / `user_id` / `member_id` / `source`） | 管理员 |
| POST | `/official-articles` | 发布 | 管理员 |
| GET | `/official-articles/{id}` | 详情 | 管理员 |
| PUT | `/official-articles/{id}` | 编辑 | 管理员 |
| PATCH | `/official-articles/{id}/status` | 审核 | 管理员 |
| DELETE | `/official-articles/{id}` | 删除 | 管理员 |
| GET | `/official-articles/detail/{id}` | 公开详情（仅已通过） | 公开 |
| POST | `/official-articles/{id}/view` | 记录访问量 | 公开 |

> 官号文章的**点赞 / 收藏 / 评论**不单开接口，统一走 `/posts/{带偏移的 id}/...`，见第九节。

### 站内消息 `/messages`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/messages` | 消息列表（按类型筛选 + 分页） |
| GET | `/messages/unread-count` | 未读数 |
| POST | `/messages/{id}/read` | 单条已读 |
| POST | `/messages/read-all` | 全部已读 |

### 简历 `/resume`（管理员）

六组前缀形状完全一致：`/resume/personal-infos`、`/resume/educations`、`/resume/work-experiences`、
`/resume/projects`、`/resume/evaluations`、`/resume/skill-tags`，每组提供：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `<集合>` | 分页列表 + 搜索 |
| POST | `<集合>` | 新增 |
| GET | `<集合>/{id}` | 详情 |
| PUT | `<集合>/{id}` | 更新 |
| DELETE | `<集合>/{id}` | 删除 |
| PATCH | `<集合>/{id}/status` | 启用 / 停用 |

另有 `POST /resume/personal-infos/upload-avatar`（上传个人头像，返回 URL，不自动绑定）。

### 个人网站对外 `/resume/public` · `/site`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/resume/public/profiles` | 整份简历（个人信息 + 教育 + 工作含项目 + 评价），只出启用数据 | 公开 |
| GET | `/site/welcome` | 首页欢迎语（主标题 / 副标题 / 祝福语） | 公开 |
| GET | `/site/about/access` | 「关于我」是否需要密码 | 公开 |
| POST | `/site/about/verify` | 校验访问密码 | 公开 |
| GET/PUT | `/site/admin/welcome` | 读取 / 更新欢迎语 | 管理员 |
| GET/PUT | `/site/admin/about-password` | 查看 / 设置密码开关与新密码 | 管理员 |

### 系统 `/system`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/system/health` | 健康检查（含数据库探活） | 公开 |
| GET | `/system/info` | 运行信息、方言、各表行数 | 管理员 |
| GET | `/system/dashboard` | 首页统计卡片 + 最近注册会员 | 登录 |

### 静态资源

| 路径 | 说明 |
| --- | --- |
| `/api/v1/static/avatars/{会员ID}/{filename}` | 会员头像（`UPLOAD_DIR` 托管） |
| `/api/v1/static/backgrounds/{会员ID}/{filename}` | 会员背景图 |
| `/api/v1/static/posts/{filename}` | 动态图片（`posts/` 平铺） |
| `/api/v1/static/resume-avatars/{filename}` | 简历个人头像（`resume-avatars/` 平铺） |
| `/api/v1/assets/*` | 内置资源（`default-avatar.svg`） |

> 全部挂在 API 前缀下，前端 Vite 代理与 Nginx `/api` 反代可直接复用。

### 响应约定

- 成功：直接返回数据体；分页统一 `{ items, total, page, page_size, pages }`。
- 失败：`{ "code": 40100, "message": "…", "data": null }`，
  配合 HTTP 状态码（400/401/403/404/409/422/500）。

---

## 八、账号体系与认证

### 8.1 两张账号表

| 维度 | `system_auth_admin_user` | `member_account_info` |
| --- | --- | --- |
| 创建方式 | 管理员后台创建 | 邮箱自助注册 |
| 登录账号 | 用户名 | 邮箱 |
| 权限 | admin / editor / user | 无后台权限，只能操作自己的资料 |
| 令牌 `scope` | `staff` | `member` |
| 资料 | 昵称、角色、启用状态 | 10 位会员编号、昵称、头像、背景图、性别、生日、手机号、简介、地区 |

**令牌隔离**：`app/core/security.py` 在 payload 里写入 `scope`，`app/api/deps.py` 提供
`get_current_user`（staff）/ `get_current_member`（member）/ `get_current_admin`。
会员令牌访问后台接口返回 40104「令牌使用范围不正确」，反之亦然；会员被禁用后已签发令牌立即失效。

### 8.2 注册与找回密码流程

```
① 注册
  POST /member/auth/send-code      {email, scene:"register"}
  POST /member/auth/register       {email, code, password, confirm_password}
                                     ├ 邮箱验证标记为已验证
                                     ├ secrets 生成 10 位唯一 member_no（范围 1000000000-9999999999）
                                     └ 默认昵称 + 默认头像

② 登录
  POST /member/auth/login          {email, password} → access / refresh（scope=member）

③ 完善资料
  PUT  /member/profile             文本字段
  POST /member/profile/avatar      返回 URL 并自动写入头像字段
  POST /member/profile/background  同上

④ 忘记密码（未登录）
  POST /member/auth/send-code      {email, scene:"reset_password"}
  POST /member/auth/reset-password {email, code, new_password, confirm_password}

⑤ 修改密码（已登录）
  POST /member/send-code           发到当前账号邮箱（scene=change_password）
  POST /member/profile/change-password
```

### 8.3 验证码机制

| 机制 | 说明 |
| --- | --- |
| 生成 | `secrets.randbelow`，非伪随机 |
| 有效期 | 10 分钟 |
| 重发冷却 | 60 秒（同邮箱 + 场景） |
| 失败上限 | 5 次，超出作废 |
| 一次性 | 校验通过写 `used_at` |
| 场景隔离 | 注册码不能用于重置密码 |
| 本地调试 | `MAIL_ENABLED=false` 时打日志，`EMAIL_CODE_DEBUG_RETURN=true` 时响应带 `debug_code` |

### 8.4 图片上传与地址解析

- **校验**：后缀白名单 + 大小上限 + 魔术字节，防改名可执行文件。
- **HEIC / HEIF**：落盘前转 JPEG（`pillow-heif`），按 88/75/60 逐档降质量压到限制内，并纠正 EXIF 旋转。
- **落盘**：一个会员一个目录，覆盖上传会清掉旧图，删除会员时整目录清理；已做路径穿越防护。
- **地址**：`avatar_url` / `background_url` 由资料接口直接返回，前端不需要单独取图接口。
  头像缺省回退 `DEFAULT_AVATAR`，背景图缺省为空串；文件名带随机串，重传后地址必变。

### 8.5 演示数据

`scripts/init_db.py` 在表为空时写入下表（密码统一 `members123`）：

| 邮箱 | 昵称 | 性别 | 生日 | 地区 | 状态 |
| --- | --- | --- | --- | --- | --- |
| alice@example.com | Alice | 女 | 1996-05-20 | 上海 | 启用 |
| bob@example.com | Bob | 男 | 1992-11-03 | 北京 | 启用 |
| carol@example.com | Carol | 保密 | - | - | 禁用 |

---

## 九、内容体系（动态 / 官号文章 / 互动 / 消息）

### 9.1 两种内容，一条流

动态存 `article_post_info`，官号文章存 `article_official_info`。为了 App 不必区分，
`app/services/article_feed.py` 把文章映射成帖子出参：

- `kind = "article"` 标识来源，`article_id` / `article_url` / `article_source` / `publisher` 等附加字段；
- `id = ARTICLE_ID_OFFSET(1_000_000_000) + article.id`，避免与帖子主键撞号；
- 详情 / 访问量 / 点赞 / 收藏 / 评论**全部复用 `/posts/{id}/...`**，服务层用
  `is_article_id()` 判断后路由到文章相关仓储；评论 id 同样带偏移；
- `GET /posts/latest|hot|recommend|following|by-member` 与「我的获赞 / 被评论」都把两类内容合并排序。

### 9.2 审核规则

- 动态与评论发布后为 `pending`，后台 `PATCH .../status` 改为 `approved` / `rejected`，**终态不可再改**。
- 只有 `approved` 的内容对外可见；被拒绝的动态作者可 `PATCH /posts/{id}` 修改后重新提交。
- 官号文章同样走 `pending → approved / rejected`。

### 9.3 互动与消息

| 互动 | 存储 | 约束 |
| --- | --- | --- |
| 点赞 | `article_post_like` / `article_official_like` | 幂等，仅已通过内容 |
| 收藏 | `article_post_favorite` / `article_official_favorite` | 幂等 |
| 评论 | `article_post_comment` / `article_official_comment` | 默认待审核 |
| 关注 | `member_account_follow` | 幂等，`GET /members/me/following` |

`member_account_message` 承载站内消息（`MessageType`：评论 / 点赞 / 关注 / 审核结果 / 公告），
提供未读数、单条已读、全部已读。

---

## 十、个人网站（简历 + 站点设置）

### 10.1 六组简历数据

| 集合 | 表 | 说明 |
| --- | --- | --- |
| `personal-infos` | `resume_base_personal_info` | 姓名、头像、性别、生日、手机号、邮箱、现居城市、求职意向、当前状态、工作年限、个人主页、备注 |
| `educations` | `resume_base_education` | 绑定 `personal_info_id` |
| `work-experiences` | `resume_base_work` | 绑定 `personal_info_id` |
| `projects` | `resume_base_project` | **必须绑定公司经历**（`work_id`） |
| `evaluations` | `resume_base_evaluation` | 绑定 `personal_info_id` |
| `skill-tags` | `resume_base_skill_tag` | 一条 = 分类 + 多个标签，标签用分号分隔，后端去重规整 |

每条记录都有 `is_active` + `sort`，对外接口按 `sort` 升序，只出「自身与各级父级都启用」的数据。

### 10.2 对外合并接口

`GET /resume/public/profiles?personal_info_id=&limit=` —— 一次返回整份简历：

```json
[
  {
    "personal_info": {},
    "educations": [],
    "work_experiences": [{ "projects": [] }],
    "evaluations": [],
    "skill_tags": []
  }
]
```

传 `personal_info_id` 只取一人（不存在或已停用返回 404），不传取所有启用中的人。

### 10.3 站点设置

`site_setting` 是单例（`id=1`）：

- 欢迎语三件套：`welcome_title` / `welcome_subtitle` / `welcome_blessing`；
- 「关于我」密码：只存 bcrypt 哈希（`app/core/site_password.py`，先 SHA-256 预处理以支持中文长密码），
  默认密码 `123456`，`about_password_text` 仅供后台回显。

---

## 十一、数据库与结构演进

### 11.1 启动时自动做的事

`app/db/init_db.py` 按顺序执行（全部幂等）：

1. `create_all()` 建出缺失的表；
2. `drop_legacy_tables()` 删除下线功能遗留的 8 张表（`DROP_LEGACY_TABLES=false` 可关）：
   `dish_order_item`、`dish_order_info`、`dish_base_spec`、`dish_base_tag_relation`、
   `dish_base_info`、`dish_base_category`、`dish_base_tag`、`countdown_base_info`；
3. `sync_missing_columns()` 补「模型有、库里没有」的列（只 `ADD COLUMN`）；
4. `sync_column_types()` 放宽长度不足的字符串列（只放宽不放窄，如 `member_no` 6 → 10 位）；
5. 写入初始管理员、演示会员、站点设置单例。

因此**日常升级只需拉代码 + 重启（或重建镜像）**，不需要手工迁移命令。

### 11.2 Alembic

结构版本由 5 个迁移文件管理，连接串复用 `settings.DATABASE_URL`：

```powershell
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "xxx"
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m alembic downgrade -1
./.venv/Scripts/python.exe -m alembic -x db_url="postgresql+psycopg://..." upgrade head
./.venv/Scripts/python.exe -m alembic upgrade head --sql
```

已有库第一次接入 Alembic（库里还没有 `alembic_version`）要先建基线：

```powershell
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "baseline"
./.venv/Scripts/python.exe -m alembic stamp head
```

> 只有「不止于加列」的变更（改类型 / 删列 / 加约束 / 数据回填）才必须走 Alembic。

### 11.3 迁移到 PostgreSQL / MySQL

```powershell
# 1. 装驱动
./.venv/Scripts/python.exe -m pip install "psycopg[binary]"      # PG
./.venv/Scripts/python.exe -m pip install PyMySQL                # MySQL

# 2. 目标库先建空库，再迁移数据
./.venv/Scripts/python.exe scripts/migrate_database.py `
  --source "sqlite:///./data/app.db" `
  --target "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/admin_db" `
  --create-tables --truncate
```

脚本按外键顺序分批写入，自动跳过源库不存在的列，PostgreSQL 下重置自增序列，最后输出行数比对。
参数：`--source` / `--target` / `--create-tables` / `--truncate` / `--tables` /
`--batch-size`（默认 500）/ `--verify-only`。

改完 `.env` 的 `DATABASE_URL` 重启，用 `GET /api/v1/system/info` 的 `database_dialect` 确认。

### 11.4 表命名规范

`一级功能_二级功能_功能`，第三段常用 `info`（主表）/ `item`（明细）/ `relation`（关联表）：

| 一级 | 二级 | 表 |
| --- | --- | --- |
| `system` | `auth` | `system_auth_admin_user` |
| `member` | `account` | `member_account_info`、`member_account_follow`、`member_account_message`、`member_account_email_code` |
| `article` | `post` | `article_post_info`、`article_post_like`、`article_post_favorite`、`article_post_comment` |
| `article` | `official` | `article_official_info`、`article_official_like`、`article_official_favorite`、`article_official_comment` |
| `resume` | `base` | `resume_base_personal_info`、`resume_base_education`、`resume_base_work`、`resume_base_project`、`resume_base_evaluation`、`resume_base_skill_tag` |
| `site` | — | `site_setting` |

新增模型必须同时在 `app/models/__init__.py` 导出，否则 `Base.metadata` 不会注册该表。

---

## 十二、测试

```powershell
./.venv/Scripts/python.exe -m pytest                 # 全部
./.venv/Scripts/python.exe -m pytest -v              # 详细
./.venv/Scripts/python.exe -m pytest tests/test_resume.py -v
```

测试使用内存 SQLite，上传写入系统临时目录，验证码不发真实邮件。

| 测试文件 | 覆盖点 |
| --- | --- |
| `test_api.py` | 健康检查、后台登录、令牌校验、后台账号 CRUD |
| `test_member.py` | 会员资料、后台会员管理、头像 / 背景图、地区字段、令牌隔离 |
| `test_member_auth.py` / `test_member_register_code.py` / `test_member_reset_code.py` | 注册 / 登录 / 验证码场景与冷却 |
| `test_email_code_service.py` | 验证码生成、限流、尝试次数 |
| `test_member_follow.py` | 关注 / 取关 / 关注流 |
| `test_post.py` / `test_post_comment.py` | 动态发布审核、点赞收藏、评论、获赞/被评论列表 |
| `test_official_article.py` / `..._interaction.py` / `..._comment.py` / `..._feed.py` | 官号文章 CRUD、互动、与动态合流 |
| `test_messages.py` | 消息生成、未读数、已读 |
| `test_resume.py` / `test_resume_public.py` | 六组简历 CRUD、启停、对外合并接口 |
| `test_site.py` | 欢迎语、关于我密码 |
| `test_storage.py` | 魔术字节（含 HEIC）、HEIC → JPEG |
| `test_schema_sync.py` | 自动补列、旧数据不丢、幂等 |
| `test_legacy_cleanup.py` / `test_retired_features.py` | 下线表清理与已移除接口不再暴露 |

---

## 十三、生产部署

上线前必须：`DEBUG=false`、`EMAIL_CODE_DEBUG_RETURN=false`、更换 `SECRET_KEY`、
`DATABASE_URL` 指向正式库、`BACKEND_CORS_ORIGINS` 填真实前端域名。

### 13.1 单机 / Gunicorn

```powershell
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

```bash
pip install "uvicorn[standard]" gunicorn
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 \
  --access-logfile - --error-logfile -
```

> 多 worker 与 SQLite 配合不佳，生产建议 PG / MySQL。

### 13.2 systemd

```ini
# /etc/systemd/system/fastapi-admin.service
[Unit]
Description=后台管理系统 FastAPI Backend
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/fastapi-admin-backend
Environment="PATH=/opt/fastapi-admin-backend/.venv/bin"
ExecStart=/opt/fastapi-admin-backend/.venv/bin/gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now fastapi-admin
```

### 13.3 Nginx

```nginx
server {
    listen 80;
    server_name api.example.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 可选：同域托管前端构建产物
    location / {
        root /var/www/admin;
        try_files $uri $uri/ /index.html;
    }
}
```

### 13.4 Docker（后端容器 + 宿主机上的 PG 容器）

`docker-compose.yml` 只有一个 backend 服务，`build.context` 指向 GitHub 仓库，
服务器上不需要源码；`.env.docker.example` 是变量模板（`cp` 成 `.env`）。

```bash
# 0) Dockerfile / compose / .env.docker.example / .dockerignore 必须先 push 到仓库
# 1) 目标库要事先存在（后端只建表不建库）
docker exec -it <PG容器名> psql -U postgres -c "CREATE DATABASE admin_db;"

# 2) 准备配置
mkdir -p /opt/fastapi-admin && cd /opt/fastapi-admin
cp .env.docker.example .env

# 3) 构建启动
docker compose up -d --build
docker compose logs -f backend
curl http://127.0.0.1:8000/api/v1/system/health
```

关键变量：`PG_HOST`（默认 `host.docker.internal`，**不要写 127.0.0.1**）、`PG_PORT`（默认 5452）、
`PG_USER` / `PG_PASSWORD` / `PG_DB`、`PYTHON_IMAGE`、`APT_MIRROR`、`PIP_INDEX_URL`。

镜像入口：

```dockerfile
CMD ["sh", "-c", "python scripts/init_db.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
```

**常见坑**

| 现象 | 原因与处理 |
| --- | --- |
| `Dockerfile not found` | 仓库里还没有 Dockerfile，先 push |
| `pull access denied` / `manifest unknown` | 纯构建服务被当成拉取；compose 已加 `pull_policy: build` |
| `Unsupported config option ... pull_policy` | Compose v1，升级到 v2 |
| `failed to resolve source metadata ... 403` | Docker daemon 的 registry mirror 失效；删 `registry-mirrors` 或给 `PYTHON_IMAGE` 填完整仓库地址 |
| `pip install` 超时 | 换 `PIP_INDEX_URL`；apt 慢则设 `APT_MIRROR` |
| 连不上数据库 | 容器内不能用 `127.0.0.1`，用 `host.docker.internal`（Linux 需 compose 的 `extra_hosts: host-gateway`） |
| `database "admin_db" does not exist` | 先建库 |
| 改了 `.env` 不生效 | 变量只在创建容器时注入，需 `--force-recreate` |
| 容器时区不对 | 设 `TZ=Asia/Shanghai` |
| 上传图片想导出 | 命名卷 `uploads`：`docker cp admin-backend:/app/data/uploads ./` |
| 报缺列 | 正常启动会自动补列；仍失败说明变更不止加列，跑 `alembic upgrade head` |

**更稳的网络接法**：把两个容器接到同一个自定义网络，用容器名 + 5432 直连，少一层 NAT。

---

## 十四、与客户端项目的对接

| 客户端 | 仓库 | 说明 |
| --- | --- | --- |
| 后台管理 | `fastapi-admin-frontend` | Vue 3 + Vite + Element Plus；`VITE_API_BASE_URL=/api/v1` |
| 移动端 App | `flet-post-app` | Flet；默认 `http://fastapi.277686.xyz/api/v1`，App 内可改服务器地址 |

- 通讯方式仅 HTTP（REST + JSON），后端不渲染页面，客户端不直连数据库。
- 跨域：前后端不同域时，把前端地址加入 `BACKEND_CORS_ORIGINS`：

```dotenv
BACKEND_CORS_ORIGINS=http://localhost:5173,https://admin.example.com
```

- 认证：登录后携带 `Authorization: Bearer <access_token>`；401 时用 `refresh_token`
  调 `/auth/refresh` 续期，失败再跳登录页。
- 上传文件与内置资源都在 `/api` 前缀下（`/api/v1/static`、`/api/v1/assets`），
  同域反代一条规则即可覆盖。
- 接口契约以 `/docs` 的 OpenAPI 文档为准。

---

## 附：常见问题

| 问题 | 排查方向 |
| --- | --- |
| 启动报 `database is locked` | SQLite 并发写限制，改用 PG / MySQL |
| 前端请求被浏览器拦截 | `BACKEND_CORS_ORIGINS` 未包含前端域名（注意 localhost 与 127.0.0.1 要一致） |
| 401「登录状态已过期」 | access_token 过期，用 refresh_token 刷新 |
| 收不到注册验证码 | `MAIL_ENABLED=false` 时不会真实发信：看响应 `debug_code` 或日志 `[用户中心]` |
| 提示「发送过于频繁」 | 同邮箱 + 场景 60 秒冷却，可设 `EMAIL_CODE_RESEND_SECONDS=0` 本地关闭 |
| 提示「令牌使用范围不正确」（40104） | 会员令牌访问了后台接口，或反之 |
| 图片 404 | 检查 `UPLOAD_DIR` 是否可写、Nginx 是否放行 `/api/v1/static/` |
| 生产环境验证码泄露 | `EMAIL_CODE_DEBUG_RETURN=false` 且 `DEBUG=false` |
| 密码校验 422 | 密码需 6–64 位且同时包含字母与数字 |
| 迁移后 PG 主键冲突 | 脚本已 `setval`；若手工插过数据需重跑迁移 |
