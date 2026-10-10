# 后台管理系统 · FastAPI 后端

基于 **FastAPI + SQLAlchemy 2.0 + Pydantic V2** 的分层后台接口系统，本地默认使用零配置的 SQLite，
可通过一个脚本「暴力迁移」到 PostgreSQL / MySQL。

系统显示名称由 `PROJECT_NAME` 统一控制（默认 `后台管理系统`），会同步出现在接口文档标题、
根路径响应、后台「系统信息」卡片与邮件标题中。

本项目可**独立部署**，与前端项目 `fastapi-admin-frontend` 之间仅通过 HTTP 接口通讯。

---

## 目录

- [一、项目简介](#一项目简介)
- [二、技术栈](#二技术栈)
- [三、分层架构设计](#三分层架构设计)
- [四、目录结构与各文件功能](#四目录结构与各文件功能)
- [五、快速开始（初始化与启动）](#五快速开始初始化与启动)
- [六、环境变量说明](#六环境变量说明)
- [七、接口清单](#七接口清单)
- [八、用户中心（会员体系）](#八用户中心会员体系)
- [九、点菜菜单与订单体系](#九点菜菜单与订单体系)
- [十、数据库迁移：SQLite → PostgreSQL / MySQL](#十数据库迁移sqlite--postgresql--mysql)
- [十一、数据库结构版本管理（Alembic）](#十一数据库结构版本管理alembic)
- [十二、测试](#十二测试)
- [十三、生产部署](#十三生产部署)
- [十四、与前端项目的对接](#十四与前端项目的对接)

---

## 一、项目简介

一个「拿来即用」的后台接口骨架，包含四块可直接复用的能力：

| 能力 | 说明 |
| --- | --- |
| 后台账号认证鉴权 | 账号密码登录、JWT（access + refresh）、角色权限（admin / editor / user） |
| 用户中心（会员） | 邮箱验证码注册（自动分配 6 位唯一会员编号）、登录、忘记密码、个人资料（昵称/头像/性别/生日/简介）、头像上传 |
| 点菜菜单与订单 | 菜品（菜名/图片/价格/库存）、**多套餐与售卖规则**（起购 / 限购 / 每日限量 / 供应时段）、分类与标签、**销量统计**、下单与订单管理闭环 |
| 通用后台 CRUD | 后台用户管理、**会员管理**（查看 / 修改 / 启禁用 / 重置密码 / 删除）、菜品管理、订单管理 |
| 分层基础设施 | 统一配置、统一异常、统一分页、请求日志、跨域、邮件、文件上传、初始化与迁移脚本 |
| 部署方式 | 单机 / Gunicorn / systemd / Nginx 反代，以及 **Docker 容器（可对接另一个容器里的 PostgreSQL）** |

设计目标：**高内聚**（每种职能只出现在固定的一层里）、**低耦合**（上层依赖下层接口，替换任一层的实现不影响其他层）。

> **两套账号体系互不通用**：`system_auth_admin_user` 表是**后台账号**（管理员创建、带权限），`member_account_info` 表是**用户中心注册用户**（邮箱自助注册、无后台权限）。
> 两者签发的 JWT 带不同的 `scope`（`staff` / `member`），用户中心令牌无法访问任何后台接口，后台令牌也无法访问用户中心接口。
>
> 表名遵循统一的 `一级功能_二级功能_功能` 规范（见 [11.3](#113-表命名规范与改名)），后台账号与前台用户从表名上一眼可辨。

---

## 二、技术栈

| 组件 | 版本 | 用途 |
| --- | --- | --- |
| Python | ≥ 3.10（已在 3.13 验证） | 运行环境 |
| FastAPI | 0.115.6 | Web 框架 / 自动生成 OpenAPI 文档 |
| Uvicorn | 0.34.0 | ASGI 服务器 |
| SQLAlchemy | 2.0.36 | ORM（2.0 声明式风格） |
| Pydantic / pydantic-settings | 2.10.4 / 2.7.0 | 数据校验与配置管理 |
| Alembic | 1.14.0 | 数据库结构版本管理 |
| PyJWT + bcrypt | 2.10.1 / 4.2.1 | 令牌签发与密码哈希 |
| smtplib（标准库） | — | 用户中心发送邮箱验证码，无需额外依赖 |
| psycopg / PyMySQL | 3.2.3 / 1.1.1 | 迁移到 PG / MySQL 时的驱动 |

---

## 三、分层架构设计

请求自上而下穿过各层，**每一层只依赖它下面的一层**：

```
HTTP 请求
   │
   ▼
┌──────────────────────────────────────────────────────────────┐
│ 中间件层 Middlewares      CORS、请求日志、Request-Id、耗时统计 │
├──────────────────────────────────────────────────────────────┤
│ 接口层 API (Controller)   路由、参数校验(Pydantic)、鉴权依赖   │
│  app/api/**                 只做「收参 → 调服务 → 返回」       │
├──────────────────────────────────────────────────────────────┤
│ 服务层 Services           业务规则、组合仓储、事务边界(commit)  │
│  app/services/**            抛语义化异常，不关心 HTTP          │
├──────────────────────────────────────────────────────────────┤
│ 仓储层 Repositories       纯数据访问，只 flush 不 commit       │
│  app/repositories/**        唯一可以出现 SQLAlchemy 语句的地方 │
├──────────────────────────────────────────────────────────────┤
│ 模型层 Models              ORM 表结构定义                      │
│  app/models/**                                                 │
└──────────────────────────────────────────────────────────────┘
   ▲
   │ 横切关注点（被各层共用，不反向依赖上层）
   ├── core/    配置、安全、日志、异常
   ├── schemas/ 出入参 DTO
   └── db/      Base、Engine、Session、初始化
```

**关键约束（保证低耦合）**

1. 接口层不写 SQL、不写业务规则，只依赖服务层的接口。
2. 服务层不直接使用 `select()` / `Session.query()`，所有数据访问都走仓储层。
3. 仓储层不写业务判断，只提供数据操作；**只 `flush` 不 `commit`**，
   事务提交统一由服务层控制，从而支持「多步操作原子提交」。
4. 服务层抛出的是 `NotFoundError` / `ConflictError` 等语义化异常（`app/core/exceptions.py`），
   由全局异常处理器统一翻译成 HTTP 响应，业务与协议解耦。
5. 依赖注入集中在 `app/api/deps.py`，测试时可用 `app.dependency_overrides` 整体替换。

---

## 四、目录结构与各文件功能

```
fastapi-admin-backend/
├── app/
│   ├── __init__.py                     包声明与版本号
│   ├── main.py                         应用入口：装配中间件 / 路由 / 异常处理 / 生命周期
│   │
│   ├── core/                           ★ 横切关注点
│   │   ├── config.py                   全局配置（读取 .env，pydantic-settings）
│   │   ├── security.py                 密码哈希（bcrypt）、JWT 签发/解析、令牌作用域
│   │   ├── exceptions.py               业务异常 + 全局异常处理器注册
│   │   ├── mailer.py                   邮件发送（SMTP / 未启用时只打日志），验证码邮件模板
│   │   ├── storage.py                  通用图片上传：后缀/大小/魔术字节校验、落盘、旧文件清理
│   │   ├── logging.py                  日志格式与初始化
│   │   └── utils.py                    通用工具（UTC 时间戳、本地时间、供应时段判定、6 位随机编号）
│   │
│   ├── db/                             ★ 数据访问基础设施
│   │   ├── base.py                     SQLAlchemy DeclarativeBase
│   │   ├── session.py                  引擎构建（自动适配 SQLite/PG/MySQL）、会话工厂、get_db
│   │   └── init_db.py                  建表 + 初始管理员 + 演示会员/菜品数据（幂等）
│   │
│   ├── models/                         ★ ORM 模型层
│   │   ├── mixins.py                   主键 / 时间戳 Mixin
│   │   ├── user.py                     后台账号表 system_auth_admin_user + UserRole 枚举
│   │   ├── member.py                   注册用户表 member_account_info（含 6 位唯一编号）+ MemberGender
│   │   ├── email_code.py               邮箱验证码表 + EmailScene 枚举（场景）
│   │   ├── dish.py                     菜品域：分类 / 标签 / 菜品 / 套餐规格（含售卖规则）
│   │   ├── dish_order.py               订单域：订单、订单明细、状态流转规则
│   │   └── __init__.py                 统一导出（新增模型必须在此注册）
│   │
│   ├── schemas/                        ★ DTO 层
│   │   ├── common.py                   分页结果、通用消息体
│   │   ├── user.py                     后台账号出入参（含密码强度校验）
│   │   ├── member.py                   会员注册/登录/资料/后台管理出入参
│   │   ├── email.py                    验证码发送出入参
│   │   ├── dish.py                     菜品域出入参（分类 / 标签 / 菜品 / 套餐 / 点菜菜单）
│   │   ├── dish_order.py               订单出入参（下单、明细、状态、统计）
│   │   ├── auth.py                     登录 / 令牌模型
│   │   ├── system.py                   健康检查、系统信息、首页统计
│   │   └── __init__.py                 统一导出
│   │
│   ├── repositories/                   ★ 仓储层（数据访问）
│   │   ├── base.py                     通用 CRUD/分页/统计基类
│   │   ├── user_repository.py          后台账号表专属查询
│   │   ├── member_repository.py        会员表专属查询（含性别/新注册统计）
│   │   ├── email_code_repository.py    验证码查询、作废、尝试次数
│   │   ├── dish_repository.py          分类 / 标签 / 菜品 / 套餐查询与统计
│   │   ├── dish_order_repository.py    订单查询、状态计数、按明细聚合销量
│   │   └── __init__.py
│   │
│   ├── services/                       ★ 服务层（业务逻辑）
│   │   ├── auth_service.py             后台账号：登录 / 刷新令牌 / 改密
│   │   ├── user_service.py             后台账号 CRUD + 最后管理员保护等规则
│   │   ├── email_code_service.py       验证码生成、限流、发送、校验
│   │   ├── member_auth_service.py      会员：注册 / 登录 / 刷新 / 重置密码 / 改密
│   │   ├── member_service.py           会员资料 + 头像上传 + 后台管理
│   │   ├── dish_service.py             分类 / 标签 / 菜品 / 套餐管理 + 点菜菜单查询
│   │   ├── dish_order_service.py       下单校验、库存销量联动、取消回滚、状态流转、统计
│   │   ├── system_service.py           健康检查 / 系统信息 / 首页统计
│   │   └── __init__.py
│   │
│   ├── api/                            ★ 接口层
│   │   ├── deps.py                     依赖注入：Session、当前用户/会员、管理员校验、分页、各 Service
│   │   └── v1/
│   │       ├── router.py               v1 路由聚合
│   │       └── endpoints/
│   │           ├── auth.py              /auth/*         后台账号登录、刷新、改密
│   │           ├── users.py             /users/*        后台账号管理（仅管理员）
│   │           ├── member_auth.py       /member/auth/*  用户中心：验证码、注册、登录、重置密码
│   │           ├── member_profile.py    /member/*       用户中心：我的资料、头像、改密
│   │           ├── members.py           /members/*      后台会员管理（仅管理员）
│   │           ├── menu.py             /menu/*         点菜菜单：分类、菜品、下单、我的订单
│   │           ├── dishes.py           /dishes/*       后台菜品 / 分类 / 标签管理
│   │           ├── dish_orders.py      /dish-orders/*  后台订单管理与统计
│   │           └── system.py            /system/*       健康检查、系统信息、首页统计
│   │
│   └── middlewares/
│       └── request_log.py              请求日志中间件（X-Request-Id、耗时、静态资源跳过）
│
├── alembic/                            数据库结构迁移
│   ├── env.py                          连接串复用 settings.DATABASE_URL
│   ├── script.py.mako                  迁移脚本模板
│   └── versions/                       迁移脚本存放目录
├── alembic.ini                         Alembic 配置
│
├── scripts/
│   ├── init_db.py                      手动初始化数据库（建表 + 初始数据）
│   └── migrate_database.py             ★ SQLite → PG/MySQL 数据迁移工具
│
├── tests/
│   ├── conftest.py                     测试夹具（内存 SQLite、TestClient、鉴权头）
│   ├── test_api.py                     认证 / 后台账号主链路冒烟测试
│   ├── test_member.py                  用户中心全流程测试
│   └── test_dish.py                    点菜菜单、套餐规则与订单全流程测试
│
├── data/                               SQLite 数据文件目录（git 忽略，自动创建）
├── run.py                              开发环境启动脚本
├── requirements.txt                    依赖清单
├── pytest.ini                          pytest 配置
│
├── Dockerfile                          ★ 后端镜像（Python 3.13-slim + 非 root + 健康检查）
├── .dockerignore                       构建上下文排除规则（不含 .env / data）
├── docker-compose.yml                  ★ 后端容器编排，连接宿主机上另一个 PG 容器
├── .env.docker.example                 compose 变量模板（cp 成 .env 使用，含 PG 连接信息）
│
├── .env.example                        环境变量模板
└── .gitignore
```

---

## 五、快速开始（初始化与启动）

> 以下命令以 Windows PowerShell 为例，Linux/macOS 把 `.venv/Scripts/python` 换成 `.venv/bin/python` 即可。

### 1. 创建虚拟环境并安装依赖

```powershell
cd fastapi-admin-backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install --upgrade pip
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 2. 准备配置文件

```powershell
Copy-Item .env.example .env
```

`.env` 中至少确认两项：`SECRET_KEY`（生产必须改）与 `DATABASE_URL`（默认 SQLite，无需修改）。

### 3. 初始化数据库

```powershell
# 建表 + 创建管理员 + 写入演示会员/菜品数据（幂等，可重复执行）
./.venv/Scripts/python.exe scripts/init_db.py
```

默认会创建：

- 后台账号 `admin / admin123`（可用 `.env` 中的 `FIRST_SUPERUSER_*` 修改）
- 3 个用户中心演示会员（`alice@example.com` 等，密码统一 `members123`，详见 [8.7](#87-演示数据)）

> 也可以跳过这一步：应用启动时的生命周期钩子会自动调用 `init_db()`。

### 4. 启动服务

```powershell
# 方式一：推荐（读取 .env 的 HOST/PORT，DEBUG=true 时自动热重载）
./.venv/Scripts/python.exe run.py

# 方式二：直接使用 uvicorn
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

启动后：

| 地址 | 说明 |
| --- | --- |
| http://127.0.0.1:8000/docs | Swagger UI（点右上角 Authorize 可用 `admin/admin123` 调试） |
| http://127.0.0.1:8000/redoc | ReDoc 文档 |
| http://127.0.0.1:8000/api/v1/system/health | 健康检查 |

### 5. 验证

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"admin123\"}'
```

---

## 六、环境变量说明

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROJECT_NAME` | 后台管理系统 | 系统显示名称（文档标题、系统信息、邮件标题） |
| `DEBUG` | true | 调试模式（影响热重载） |
| `HOST` / `PORT` | 0.0.0.0 / 8000 | 监听地址与端口 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `DATABASE_URL` | sqlite:///./data/app.db | 数据库连接串（见下节） |
| `SQL_ECHO` | false | 是否打印 SQL |
| `SECRET_KEY` | 示例值 | JWT 签名密钥，**生产必须更换** |
| `ALGORITHM` | HS256 | JWT 算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | access_token 有效期（分钟） |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | 10080 | refresh_token 有效期（分钟） |
| `BACKEND_CORS_ORIGINS` | localhost:5173 等 | 允许跨域来源，逗号分隔 |
| `FIRST_SUPERUSER_*` | admin / admin123 / … | 初始管理员账号信息 |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | 10 / 200 | 分页默认值与上限 |

**用户中心（会员）相关**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAIL_ENABLED` | false | 是否真正发送邮件；false 时验证码只写入服务端日志 |
| `MAIL_HOST` / `MAIL_PORT` | smtp.example.com / 465 | SMTP 服务器与端口 |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | 空 | SMTP 登录账号（多数邮箱需使用「授权码」而非登录密码） |
| `MAIL_FROM` | 后台管理系统 <noreply@example.com> | 发件人 |
| `MAIL_USE_SSL` | true | true 用 `SMTP_SSL`，false 用 `SMTP + STARTTLS` |
| `MAIL_TIMEOUT` | 10 | 发信超时（秒） |
| `EMAIL_CODE_LENGTH` | 6 | 验证码位数 |
| `EMAIL_CODE_EXPIRE_MINUTES` | 10 | 验证码有效期 |
| `EMAIL_CODE_RESEND_SECONDS` | 60 | 同一邮箱 + 场景的重发冷却时间 |
| `EMAIL_CODE_MAX_ATTEMPTS` | 5 | 同一验证码最多允许校验失败次数 |
| `EMAIL_CODE_DEBUG_RETURN` | true | 是否在响应 `debug_code` 回显验证码（**生产必须 false**） |
| `DEFAULT_AVATAR` | /api/v1/assets/default-avatar.svg | 会员注册后的默认头像地址（内置资源，由 `app/static` 托管） |
| `UPLOAD_DIR` | ./data/uploads | 上传目录（相对路径以项目根目录为基准） |
| `IMAGE_MAX_SIZE_MB` | 5 | 图片（会员头像 / 菜品图片）大小上限 |
| `IMAGE_ALLOWED_EXTENSIONS` | jpg,jpeg,png,webp,gif | 允许的图片后缀 |

生成随机密钥：

```powershell
./.venv/Scripts/python.exe -c "import secrets;print(secrets.token_urlsafe(48))"
```

常用邮箱的 SMTP 参考（`MAIL_PASSWORD` 请填写邮箱后台生成的授权码）：

| 邮箱 | MAIL_HOST | MAIL_PORT | MAIL_USE_SSL |
| --- | --- | --- | --- |
| QQ 邮箱 | smtp.qq.com | 465 | true |
| 163 邮箱 | smtp.163.com | 465 | true |
| Gmail | smtp.gmail.com | 587 | false（STARTTLS） |
| 企业微信/腾讯企业邮 | smtp.exmail.qq.com | 465 | true |

---

## 七、接口清单

统一前缀 `/api/v1`。除标注「公开」外，均需请求头 `Authorization: Bearer <access_token>`。

### 认证 `/auth`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/auth/login` | JSON 登录，返回 access/refresh 令牌 | 公开 |
| POST | `/auth/token` | OAuth2 表单登录（Swagger 调试用） | 公开 |
| POST | `/auth/refresh` | 用 refresh_token 换新令牌 | 公开 |
| GET | `/auth/me` | 当前登录用户信息 | 登录 |
| POST | `/auth/change-password` | 修改自己的密码 | 登录 |
| POST | `/auth/logout` | 登出（前端清除令牌即可） | 登录 |

### 用户 `/users`（全部需要管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/users` | 分页列表，支持 `page` `page_size` `keyword` `role` `is_active` |
| POST | `/users` | 创建用户 |
| GET | `/users/{id}` | 用户详情 |
| PUT | `/users/{id}` | 更新用户（邮箱 / 昵称 / 角色 / 状态） |
| PATCH | `/users/{id}/status` | 启用 / 禁用 |
| PATCH | `/users/{id}/password` | 重置密码 |
| DELETE | `/users/{id}` | 删除用户 |

> 内置保护：不能删除/禁用/降级「最后一个管理员」，不能禁用或删除当前登录账号。

### 用户中心（会员端）`/member`（无需后台权限）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/member/auth/send-code` | 发送邮箱验证码（`scene=register` / `reset_password`） | 公开 |
| POST | `/member/auth/register` | 邮箱验证码注册（入参 `email` `code` `password` `confirm_password`），成功即完成邮箱验证，并**随机生成 6 位唯一会员编号**、自动生成默认昵称与默认头像 | 公开 |
| POST | `/member/auth/login` | 邮箱 + 密码登录，返回 `scope=member` 令牌 | 公开 |
| POST | `/member/auth/token` | OAuth2 表单登录（Swagger 调试用） | 公开 |
| POST | `/member/auth/refresh` | 刷新会员令牌 | 公开 |
| POST | `/member/auth/reset-password` | 忘记密码：入参 `email` `code` `new_password` `confirm_password` | 公开 |
| GET | `/member/auth/me` | 当前登录会员 | 会员 |
| POST | `/member/auth/logout` | 退出登录 | 会员 |
| GET | `/member/profile` | 查看我的资料 | 会员 |
| PUT | `/member/profile` | 修改昵称 / 头像 / 性别 / 生日 / 手机号 / 简介 | 会员 |
| POST | `/member/profile/avatar` | 上传头像（multipart，≤2MB，jpg/png/webp/gif） | 会员 |
| POST | `/member/send-code` | 已登录获取「修改密码」邮箱验证码（邮箱取当前账号，无需传参） | 会员 |
| POST | `/member/profile/change-password` | 修改密码：入参 `code` `new_password` `confirm_password` | 会员 |

### 会员管理（后台）`/members`（仅管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/members` | 分页列表，支持 `keyword`（会员编号 / 邮箱 / 昵称 / 手机号）`gender` `is_active` `email_verified` `registered_after` `registered_before` |
| GET | `/members/stats` | 会员统计（总数 / 启用 / 禁用 / 已验证 / 近 7 天新增 / 性别分布） |
| GET | `/members/{id}` | 会员详情（含昵称、头像、性别、生日、年龄、手机号、简介） |
| PUT | `/members/{id}` | 修改会员资料与启用状态 |
| PATCH | `/members/{id}/status` | 启用 / 禁用（禁用后立即无法登录，已签发令牌同步失效） |
| PATCH | `/members/{id}/password` | 重置会员密码 |
| DELETE | `/members/{id}` | 删除会员 |

### 系统 `/system`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/system/health` | 健康检查（含数据库探活） | 公开 |
| GET | `/system/info` | 运行信息、数据库方言、各表行数 | 管理员 |
| GET | `/system/dashboard` | 首页统计卡片数据 + 最近注册会员 | 登录 |

### 静态资源 `/static`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/static/avatars/{filename}` | 已上传的会员头像（由 `UPLOAD_DIR` 目录托管） |

> 挂在 API 前缀下，前端的 `/api` 代理与 Nginx 的 `/api` 反向代理可直接复用，无需额外配置静态资源规则。

### 点菜菜单与订单

会员端 `/member/**` 与点菜端 `/menu/**` 的完整说明见 [第九节](#九点菜菜单与订单体系)；
后台的 `/dishes`、`/dish-categories`、`/dish-tags`、`/dish-orders` 同样在该节列出。

### 响应约定

- 成功：直接返回数据体；分页接口返回 `{ items, total, page, page_size, pages }`。
- 失败：统一返回 `{ "code": 40100, "message": "用户名或密码错误", "data": null }`，
  并使用对应的 HTTP 状态码（400/401/403/404/409/422/500）。

---

## 八、用户中心（会员体系）

### 8.1 为什么单独建一张 `member_account_info` 表

后台账号表（`system_auth_admin_user`）是 **B 端**：由管理员创建、带角色权限、不能自助注册。
用户中心面对的是 **C 端注册用户**，字段、生命周期、权限边界都不同，因此独立建模为 `member_account_info` 表：

| 维度 | `system_auth_admin_user`（后台账号） | `member_account_info`（用户中心注册用户） |
| --- | --- | --- |
| 创建方式 | 管理员在后台创建 | 用户自助邮箱注册 |
| 登录账号 | 用户名 | 邮箱 |
| 权限 | admin / editor / user | 无后台权限，仅能操作自己的资料 |
| 令牌 `scope` | `staff` | `member` |
| 头衔/资料 | 昵称、角色、启用状态 | 6 位会员编号、昵称、头像、性别、生日、手机号、简介 |

**令牌隔离**：两个作用域的 JWT 互不通用。会员令牌访问 `/users`、`/members` 等后台接口会直接返回 401
（错误码 40104「令牌使用范围不正确」），后台令牌访问 `/member/**` 同样被拒绝。

### 8.2 完整流程

```
① 注册
   前端  ──POST /member/auth/send-code {email, scene:"register"}──▶  校验邮箱未被注册 → 生成 6 位码 → 发信
   前端  ──POST /member/auth/register  {email, code, password, confirm_password}──▶
                                      校验两次密码一致 → 校验验证码 → 创建会员（email_verified=true）
                                                                  └ 随机生成 6 位唯一会员编号（member_no）
                                                                  └ 自动生成默认昵称 + 写入默认头像

② 登录
   前端  ──POST /member/auth/login {email, password}──▶  access_token + refresh_token（scope=member）

③ 完善资料
   PUT  /member/profile        昵称 / 头像地址 / 性别 / 生日 / 手机号 / 简介
   POST /member/profile/avatar 上传头像文件 → 返回可访问 URL 并自动写入头像字段

④ 忘记密码（未登录）
   POST /member/auth/send-code      {email, scene:"reset_password"}  要求邮箱已注册
   POST /member/auth/reset-password {email, code, new_password, confirm_password}  两次密码一致才更新

⑤ 修改密码（已登录）
   POST /member/send-code                    带会员令牌 → 向当前账号邮箱发码（scene=change_password）
   POST /member/profile/change-password       {code, new_password, confirm_password}
                                              校验验证码 → 校验两次密码一致 → 更新密码（验证码一次性）
                                              └ 新密码不能与当前密码相同
```

**会员编号（`member_no`）**

注册成功时自动分配一个 **6 位纯数字**的会员编号，作为对外展示的短 ID（`member_account_info.id` 那种自增主键
不适合直接给用户看，也不适合作为业务标识）。规则：

| 项 | 说明 |
| --- | --- |
| 长度与范围 | 固定 6 位、首位不为 0，取值区间 `100000-999999`（900000 种） |
| 生成方式 | `secrets.randbelow`（`app/core/utils.generate_member_no`），非伪随机 |
| 唯一性 | 生成时先查重、重试最多 10 次；`member_account_info.member_no` 上还有**唯一索引**兜底，绝不重复 |
| 可检索 | 后台 `GET /members?keyword=<编号>` 可按编号精确查找 |
| 不可修改 | 由系统生成，资料编辑接口（会员端 / 后台）都不接受该字段 |

> 为什么不用主键 `id` 充当 6 位 ID：`dish_order_info.member_id` 等外键依赖自增主键，
> 改成随机会丢掉有序性、破坏外键语义，且写入时需要处理冲突。新增独立的业务编号是更稳妥的做法。

### 8.3 邮箱验证码机制

| 机制 | 说明 |
| --- | --- |
| 生成 | 使用 `secrets.randbelow` 生成，非伪随机数 |
| 有效期 | 默认 10 分钟（`EMAIL_CODE_EXPIRE_MINUTES`） |
| 重发冷却 | 默认 60 秒（`EMAIL_CODE_RESEND_SECONDS`），避免刷接口 |
| 失败次数 | 默认最多 5 次（`EMAIL_CODE_MAX_ATTEMPTS`），超出后该验证码作废 |
| 一次性 | 校验通过立即标记 `used_at`，同一条码不能复用 |
| 场景隔离 | 注册码不能用于重置密码（`scene` 字段区分） |
| 业务校验 | 注册场景要求邮箱未注册，重置密码场景要求邮箱已注册 |

### 8.4 本地如何拿到验证码（不配置 SMTP）

默认 `MAIL_ENABLED=false`，邮件不会真实发出，验证码会：

1. 打印在服务端日志中：`[用户中心] 未真实发送邮件，验证码 -> email=xxx scene=register code=123456`；
2. 若 `DEBUG=true` 且 `EMAIL_CODE_DEBUG_RETURN=true`，接口会直接把它回显在 `debug_code` 字段：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/member/auth/send-code `
  -H "Content-Type: application/json" `
  -d '{\"email\":\"me@example.com\",\"scene\":\"register\"}'
```

```json
{
  "email": "me@example.com",
  "scene": "register",
  "sent": false,
  "expires_in": 600,
  "resend_after": 60,
  "debug_code": "123456"
}
```

> **生产环境必须**：`MAIL_ENABLED=true` + `EMAIL_CODE_DEBUG_RETURN=false`。

### 8.5 头像上传

- 接口：`POST /member/profile/avatar`（`multipart/form-data`，字段名 `file`）
- 校验：后缀白名单 + 大小上限 + **魔术字节校验**（防止改名的可执行文件）
- 存储：`{UPLOAD_DIR}/avatars/avatar_{会员ID}_{随机串}.{ext}`
- 访问：`{API_V1_PREFIX}/static/avatars/xxx.png`，例如 `/api/v1/static/avatars/avatar_1_ab12cd34ef56.png`
- 清理：更新或删除会员时会自动移除旧的本地头像文件；路径穿越已做防护

### 8.6 后台如何管理会员

进入前端 `fastapi-admin-frontend` 的「用户列表」菜单（用户管理 ▸ 用户列表，仅 `admin` 角色可见）：

- **查看**：列表支持 关键词（邮箱/昵称/手机号）、性别、启用状态、邮箱验证状态 组合筛选；
  点「详情」查看完整资料（含年龄、验证时间、最后登录、注册时间）。
- **修改**：点「编辑」可改昵称、头像地址、性别、生日、手机号、简介与启用状态。
- **启用 / 禁用**：列表内开关一键切换。禁用后：无法登录，且**已签发的令牌立即失效**
  （每次请求都会校验会员状态）。
- **重置密码**：管理员直接设置新密码，无需邮箱验证码。
- **删除**：二次确认后删除会员及其本地头像文件。

### 8.7 演示数据

`python scripts/init_db.py` 会写入 3 个演示会员（表为空时才写入）：

| 邮箱 | 昵称 | 性别 | 生日 | 状态 | 密码 |
| --- | --- | --- | --- | --- | --- |
| alice@example.com | Alice | 女 | 1996-05-20 | 启用 | members123 |
| bob@example.com | Bob | 男 | 1992-11-03 | 启用 | members123 |
| carol@example.com | Carol | 保密 | - | 禁用 | members123 |

---

## 九、点菜菜单与订单体系

覆盖「菜品维护 → 顾客点单 → 后台接单」的完整闭环。

### 9.1 数据模型与关系

```
DishCategory 1 ──── n Dish n ──── n DishTag        （分类：一对多；标签：多对多）
    （订单表的 member_id 外键指向 user 表 —— 即用户中心注册用户）
                         │
                         1
                         │
                         n
                      DishSpec                      （套餐 / 规格：价格、库存、销量、售卖规则）

DishOrder 1 ──── n DishOrderItem n ──── 1 Dish / DishSpec   （订单明细保存下单时快照）
DishOrder   n ──── 1 Member                                 （扫码点单可为匿名）
```

| 模型 | 表 | 说明 |
| --- | --- | --- |
| `DishCategory` | `dish_base_category` | 菜品分类（热菜 / 凉菜 / 主食 / 饮品…），一个菜品属于一个分类 |
| `DishTag` | `dish_base_tag` + `dish_base_tag_relation` | 菜品标签（招牌 / 新品 / 微辣 / 素食…），一个菜品可有多个标签；带 `is_active` 启用状态 |
| `Dish` | `dish_base_info` | 菜名、图片、价格、库存、**累计销量**、单位、状态、是否推荐、排序 |
| `DishSpec` | `dish_base_spec` | 套餐 / 规格（单点 / 单人套餐 / 双人套餐…），承载独立价格、库存、销量与**售卖规则** |
| `DishOrder` | `dish_order_info` | 订单主表：订单号、桌号、会员、状态、总份数、总金额、备注、各状态时间 |
| `DishOrderItem` | `dish_order_item` | 订单明细：菜名 / 套餐名 / 图片 / 单价快照 + 数量 + 小计 |

### 9.2 菜品、套餐与规则

- **一个菜品可以有多个套餐**，每个套餐有独立的价格、库存、销量和售卖规则；
- 菜品本身也有价格与库存，**没有套餐的菜品**（如「米饭」「凉拌黄瓜」）直接按菜品自身价格与库存售卖；
- 下单口径：
  - 菜品**无套餐** → 只传 `dish_id`；
  - 菜品**有套餐** → 必须传 `spec_id`，且「菜品总库存」与「套餐库存」需同时足够。

**套餐支持的售卖规则**

| 规则 | 字段 | 说明 |
| --- | --- | --- |
| 起购份数 | `min_quantity` | 单次下单不少于该数量 |
| 每单限购 | `max_quantity_per_order` | 0 表示不限购 |
| 每日限量 | `daily_limit` | 0 表示不限量；按「本地日期」自动重置 `sold_today` |
| 供应时段 | `serve_start_time` / `serve_end_time` | "HH:MM"，留空表示全天；支持跨零点（如 22:00 - 02:00） |
| 默认选中 | `is_default` | 同一菜品仅一个默认套餐，设置时会自动取消其它套餐的默认标记 |
| 可售开关 | `is_active` | 停售后该套餐不再出现在点菜菜单中 |

> 「营业时段」与「每日限量」按**服务器本地时间**判断（`app/core/utils.py` 的 `local_now` / `local_today`），
> 而所有落库时间戳仍使用 **UTC**，两者互不影响。

### 9.3 销量是怎么算出来的

采用「**冗余计数 + 订单明细**」双重保障：

1. 下单成功时，`Dish.stock` 与 `DishSpec.stock` 各扣减对应数量，
   `Dish.sold_count`、`DishSpec.sold_count`、`DishSpec.sold_today` 同步累加（同一事务内提交）；
2. 菜品库存扣到 0 时自动置为「已售罄」，取消订单回滚库存后会恢复「在售」；
3. 取消订单（待接单 / 已接单）时按明细**原样回滚**库存与销量；
4. `GET /dish-orders/dish-sales` 会**直接按订单明细聚合**销量，可与冗余计数交叉校验；
5. 菜品列表、点菜菜单、统计卡片都直接读取 `sold_count`，避免每次实时聚合。

### 9.4 订单状态流转

```
        ┌──────────┐  接单   ┌───────────┐  完成   ┌───────────┐
        │ 待接单    │ ─────▶ │ 已接单     │ ─────▶ │ 已完成     │
        │ pending  │        │ confirmed │        │ completed │
        └────┬─────┘        └─────┬─────┘        └───────────┘
             │  取消              │  取消                （终态）
             ▼                    ▼
        ┌────────────────────────────┐
        │ 已取消 cancelled            │  ← 自动回滚库存与销量
        └────────────────────────────┘
```

- 状态只能按上图的允许路径流转，非法流转返回 400（规则定义在 `ORDER_TRANSITIONS`）；
- 「已完成 / 已取消」为终态，不能再变更；
- 会员可以在用户中心取消**自己**的订单，管理员可以在后台取消任意未完成订单。

### 9.5 接口清单

**点菜（C 端）** `/api/v1/menu` —— 浏览公开，下单可匿名

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/menu/categories` | 菜单分类（只含启用且有在售菜品的分类，附带可点数量） |
| GET | `/menu/tags` | 菜单标签（只含已启用的标签） |
| GET | `/menu/dishes` | 菜品列表，支持 `keyword` `category_id` `tag_id` `is_recommended`；默认只返回在售且有库存的菜品 |
| GET | `/menu/dishes/{id}` | 菜品详情，含全部可售套餐与售卖规则 |
| POST | `/menu/orders` | **提交订单**（带会员令牌则关联会员，否则记为扫码点单） |
| GET | `/menu/orders` | 我的订单（需会员登录） |
| GET | `/menu/orders/{id}` | 我的订单详情（需会员登录） |
| POST | `/menu/orders/{id}/cancel` | 取消我的订单（需会员登录） |

**后台菜品管理**（仅管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/dishes` | 列表（支持 `keyword` `category_id` `tag_id` `status` `is_recommended` `low_stock`）/ 新建（可同时创建多个套餐） |
| GET / PUT / DELETE | `/dishes/{id}` | 详情 / 更新 / 删除 |
| PATCH | `/dishes/{id}/status` | 上架 / 下架 / 售罄 |
| PATCH | `/dishes/{id}/stock` | 调整库存（`mode=set` 直接设置，`mode=add` 补货 / 报损） |
| POST | `/dishes/upload-image` | 上传菜品图片 |
| GET / POST | `/dishes/{id}/specs` | 套餐列表 / 新增套餐 |
| PUT / DELETE | `/dishes/{id}/specs/{spec_id}` | 更新 / 删除套餐 |
| GET | `/dishes/stats` | 菜品统计（总数 / 在售 / 库存告急 / 累计销量 / 销量排行） |
| GET / POST | `/dish-categories` | 分类列表（含菜品数，支持 `only_active`）/ 新建分类 |
| PUT / DELETE | `/dish-categories/{id}` | 更新 / 删除（分类下有菜品时不允许删除） |
| GET / POST | `/dish-tags` | 标签列表（含关联菜品数，支持 `only_active`）/ 新建标签 |
| PUT / DELETE | `/dish-tags/{id}` | 更新 / 删除标签（更新支持局部字段，如只传 `is_active`） |

**后台订单管理** `/api/v1/dish-orders`（仅管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/dish-orders` | 订单列表，支持 `keyword`（订单号/桌号）`status` `created_after` `created_before` |
| GET | `/dish-orders/{id}` | 订单详情（含明细） |
| PATCH | `/dish-orders/{id}/status` | 接单 / 完成 / 取消（取消自动回滚库存与销量） |
| DELETE | `/dish-orders/{id}` | 删除订单 |
| GET | `/dish-orders/stats` | 订单统计（各状态数量 + 今日订单数 / 营业额 / 份数） |
| GET | `/dish-orders/dish-sales` | 按订单明细聚合的菜品销量排行 |

### 9.6 下单示例

```powershell
# 1. 查看菜单（无需登录）
curl.exe "http://127.0.0.1:8000/api/v1/menu/dishes?category_id=1"

# 2. 下单：宫保鸡丁「单人套餐」x1 + 米饭 x2（米饭无套餐，不传 spec_id）
curl.exe -X POST http://127.0.0.1:8000/api/v1/menu/orders `
  -H "Content-Type: application/json" `
  -d '{\"table_no\":\"A08\",\"remark\":\"不要香菜\",\"items\":[{\"dish_id\":1,\"spec_id\":2,\"quantity\":1},{\"dish_id\":4,\"quantity\":2}]}'

# 3. 后台接单（<管理员令牌> 换成 /auth/login 返回的 access_token）
curl.exe -X PATCH http://127.0.0.1:8000/api/v1/dish-orders/1/status `
  -H "Authorization: Bearer <管理员令牌>" -H "Content-Type: application/json" `
  -d '{\"status\":\"confirmed\"}'
```

### 9.7 演示数据

`python scripts/init_db.py` 会写入（表为空时才写入）：

| 分类 | 菜品 | 价格 | 库存 | 套餐 |
| --- | --- | --- | --- | --- |
| 热菜 | 宫保鸡丁（招牌 / 微辣） | ￥38 | 50 | 单点 ￥38、单人套餐 ￥52（每日限量 20、每单限购 5、供应 10:00-22:00）、双人套餐 ￥96 |
| 热菜 | 麻婆豆腐（重辣 / 素食） | ￥26 | 40 | 单点 ￥26、下饭套餐 ￥32 |
| 凉菜 | 凉拌黄瓜（素食） | ￥16 | 30 | 无套餐（演示直接按菜品下单） |
| 主食 | 米饭 | ￥3 | 200 | 无套餐 |
| 饮品 | 柠檬茶（新品） | ￥12 | 60 | 中杯 ￥12、大杯 ￥15 |

---

## 十、数据库迁移：SQLite → PostgreSQL / MySQL

### 10.1 三种可选方式

| 方式 | 适用场景 | 说明 |
| --- | --- | --- |
| A. 仅改连接串 | 数据可丢弃的开发环境 | 改 `DATABASE_URL`，启动时自动建表 |
| B. Alembic | 需要版本化的结构变更 | 见[第十一节](#十一数据库结构版本管理alembic) |
| C. 迁移脚本 | **保留 SQLite 现有数据** | 见下方 10.3，本项目推荐生产使用 |
| D. Docker 部署 | 后端容器 + 宿主机上另一个 PG 容器 | 见 [13.5 节](#135-docker-部署后端容器--宿主机上的另一个-pg-容器) |

### 10.2 第一步：安装驱动并创建目标库

```powershell
# PostgreSQL
./.venv/Scripts/python.exe -m pip install "psycopg[binary]"

# MySQL
./.venv/Scripts/python.exe -m pip install PyMySQL
```

在目标数据库中先建好空库（编码建议 `UTF8` / `utf8mb4`）：

```sql
-- PostgreSQL
CREATE DATABASE admin_db ENCODING 'UTF8';

-- MySQL
CREATE DATABASE admin_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

### 10.3 第二步：暴力迁移数据

`scripts/migrate_database.py` 会：

1. 按 ORM 元数据在目标库创建全部表结构；
2. 反射源库结构，按**外键依赖顺序**逐表读取数据；
3. 自动跳过源库中不存在的列（兼容历史结构差异），分批（默认 500 条/批）写入；
4. PostgreSQL 下自动重置自增序列，避免后续插入主键冲突；
5. 迁移完成后逐表比对源库与目标库行数并输出报告。

```powershell
# PostgreSQL：把本地 SQLite 全量迁移过去
./.venv/Scripts/python.exe scripts/migrate_database.py `
  --source "sqlite:///./data/app.db" `
  --target "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/admin_db" `
  --create-tables --truncate

# MySQL
./.venv/Scripts/python.exe scripts/migrate_database.py `
  --source "sqlite:///./data/app.db" `
  --target "mysql+pymysql://root:root@127.0.0.1:3306/admin_db?charset=utf8mb4" `
  --create-tables --truncate

# 只迁移指定的表
... --tables system_auth_admin_user,member_account_info,dish_base_info,dish_order_info

# 只校验两个库行数是否一致，不写入任何数据
./.venv/Scripts/python.exe scripts/migrate_database.py --target "<目标库URL>" --verify-only
```

参数说明：

| 参数 | 说明 |
| --- | --- |
| `--source` | 源库 URL，默认 `sqlite:///./data/app.db` |
| `--target` | 目标库 URL，不填则用 `.env` 的 `DATABASE_URL` |
| `--create-tables` | 在目标库创建缺失的表 |
| `--truncate` | 迁移前清空目标表（**会删除目标库现有数据**） |
| `--tables` | 只迁移指定表，逗号分隔 |
| `--batch-size` | 批量写入条数，默认 500 |
| `--verify-only` | 只做行数校验 |

> ⚠️ `--truncate` 是破坏性操作，请在目标库确认无误后再执行；生产环境务必先备份。

### 10.4 第三步：切换应用连接

编辑 `.env`：

```dotenv
# PostgreSQL
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/admin_db

# 或 MySQL
DATABASE_URL=mysql+pymysql://root:root@127.0.0.1:3306/admin_db?charset=utf8mb4
```

重启服务，检查 `GET /api/v1/system/info` 中的 `database_dialect` 是否为 `postgresql` / `mysql`。

### 10.5 连接串格式速查

| 数据库 | SQLAlchemy URL | 驱动包 |
| --- | --- | --- |
| SQLite | `sqlite:///./data/app.db` | 内置 |
| PostgreSQL | `postgresql+psycopg://user:pwd@host:5432/db` | `psycopg[binary]` |
| MySQL / MariaDB | `mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4` | `PyMySQL` |

---

## 十一、数据库结构版本管理（Alembic）

连接串已复用 `settings.DATABASE_URL`，无需在 `alembic.ini` 中重复配置。

```powershell
# 1. 生成迁移脚本（对比 ORM 与当前数据库结构）
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "init tables"

# 2. 应用迁移到当前 DATABASE_URL 指向的库
./.venv/Scripts/python.exe -m alembic upgrade head

# 3. 回滚一个版本
./.venv/Scripts/python.exe -m alembic downgrade -1

# 4. 临时迁移到别的库（不改 .env）
./.venv/Scripts/python.exe -m alembic -x db_url="postgresql+psycopg://..." upgrade head

# 5. 只看 SQL 不执行
./.venv/Scripts/python.exe -m alembic upgrade head --sql
```

**已有数据库第一次接入 Alembic 的正确姿势**

项目默认用 `Base.metadata.create_all()`（`scripts/init_db.py` / 应用启动时）建表，
此时数据库里还没有 `alembic_version`。若直接 `--autogenerate`，因为表结构已经一致，
会生成一份**空迁移**。推荐的基线流程：

```powershell
# 1. 生成一份（很可能是空的）基线迁移
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "baseline"

# 2. 把当前数据库标记为已处于该版本（不会真的执行 DDL）
./.venv/Scripts/python.exe -m alembic stamp head

# 3. 之后每次修改 ORM 模型，再生成真正的增量迁移
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add xxx column"
./.venv/Scripts/python.exe -m alembic upgrade head
```

> 迁移到 PostgreSQL / MySQL 后，如果目标库的表是迁移脚本（10.3 节）创建的，
> 同样先执行 `alembic stamp head` 建立基线，再继续做增量变更。

### 11.1 删除模型后残留的旧表

`create_all()` 与 Alembic 都**不会自动删除**已经被移除模型的表。
例如早期版本的内容模块（`articles`）已下线，若你的数据库是在那之前创建的，
可以按下面的方式清理这张不再使用的表：

```powershell
# SQLite（本地开发库）
./.venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('data/app.db'); c.execute('DROP TABLE IF EXISTS articles'); c.commit(); c.close()"
```

```sql
-- PostgreSQL / MySQL
DROP TABLE IF EXISTS articles;
```

> 不清理也不影响运行：ORM 已不再映射该表，`scripts/init_db.py` 与数据迁移脚本
> 都只处理当前 `Base.metadata` 中的表。

### 11.2 给已有表补充新列

`create_all()` 同样**只建表、不改表**：新的模型字段不会自动加到已存在的表上，
此时查询会报 `no such column`。二选一处理：

```powershell
# 方式一（推荐，可回溯）：用 Alembic 生成并执行增量迁移
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add dish_base_tag.is_active"
./.venv/Scripts/python.exe -m alembic upgrade head
```

```sql
-- 方式二：手工执行等价的 DDL
ALTER TABLE dish_base_tag ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1;   -- SQLite / PostgreSQL
ALTER TABLE dish_base_tag ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1; -- MySQL
```

> 本地开发库已经补过这一列（`dish_base_tag.is_active`，历史数据默认启用）；
> 全新的数据库由 `create_all()` 直接建出带该列的完整表，无需处理。

**带唯一约束 / NOT NULL 的新列（如 `member_account_info.member_no`）**

这类列不能只加 DDL 就完事：`NOT NULL + UNIQUE` 要求历史行都有值且互不重复，
所以要「加列 → 回填 → 建唯一索引」三步走。SQLite 示例（其他库把索引语法替换即可）：

```python
# 1) 先加一个带默认值的普通列（SQLite 的 ADD COLUMN 不支持直接加 UNIQUE）
ALTER TABLE member_account_info ADD COLUMN member_no VARCHAR(6) NOT NULL DEFAULT ''

# 2) 逐行回填：用应用里的生成函数，保证 6 位且互不重复
from app.core.utils import generate_member_no
taken = set()
for row_id, current in 查询所有 (id, member_no):
    编号 = current if 合法且未占用 else 反复 generate_member_no() 直到未占用
    UPDATE member_account_info SET member_no = 编号 WHERE id = row_id

# 3) 补上唯一索引（名字与 SQLAlchemy unique=True + index=True 生成的一致）
CREATE UNIQUE INDEX IF NOT EXISTS ix_member_account_info_member_no
    ON member_account_info (member_no)
```

> 本地开发库已完成上述三步（历史用户均已回填唯一编号）；全新数据库由
> `create_all()` 直接建出 `member_no` 唯一列，无需处理。

### 11.3 表命名规范与改名

**规范：`一级功能_二级功能_功能`** —— 三段拼起来必须能完整说明这张表是什么，
禁止出现只有一两段的名字（如早期的 `user`、`dishes`）。

| 一级功能 | 二级功能 | 含义 | 现有表 |
| --- | --- | --- | --- |
| `system` | `auth` | 系统 · 认证 | `system_auth_admin_user` |
| `member` | `account` | 用户中心 · 账号 | `member_account_info`、`member_account_email_code` |
| `dish` | `base` | 菜品 · 基础数据 | `dish_base_info`、`dish_base_category`、`dish_base_tag`、`dish_base_spec`、`dish_base_tag_relation` |
| `dish` | `order` | 菜品 · 订单 | `dish_order_info`、`dish_order_item` |

第三段的常用后缀语义：

| 后缀 | 含义 | 示例 |
| --- | --- | --- |
| `info` | 主表（实体本体） | `dish_base_info`、`dish_order_info` |
| `item` | 子表 / 明细 | `dish_order_item` |
| `relation` | 多对多关联中间表 | `dish_base_tag_relation` |
| `email_code` | 邮箱验证码 | `member_account_email_code` |

> 新增表时必须遵循该规范；模型的 `__tablename__`、文件头注释、本 README 的目录树要一起更新。

**给老库改名时的注意点**（表名只影响数据库，API 路径如 `/users`、`/members` 保持不变）：

| 事项 | 说明 |
| --- | --- |
| 表本身 | `ALTER TABLE 旧名 RENAME TO 新名;`（SQLite / PostgreSQL / MySQL 均支持） |
| 外键 | SQLite 与 PostgreSQL 的 `RENAME` 会**自动改写**其它表中指向该表的外键（如 `dish_order_info.member_id`），无需手工处理；MySQL 需自行核对 |
| 索引名 | SQLAlchemy 的自动索引名跟着表名走（`ix_dishes_name` → `ix_dish_base_info_name`）。`create_all()` **不会**给已存在的表补索引，需按「列组合 + 唯一性」比对 metadata 后 DROP + CREATE 一遍 |
| 保留字 | 表名尽量避开保留字；`user` 在 PostgreSQL 中是保留字，若非要使用，手写 SQL 必须写成 `"user"`（ORM 侧 SQLAlchemy 会自动加引号） |

> 本地开发库已完成改名（10 张表 + 全部索引名 + 外键），详见 `data/app.db`。

---

## 十二、测试

```powershell
./.venv/Scripts/python.exe -m pytest            # 运行全部用例
./.venv/Scripts/python.exe -m pytest -v         # 详细输出
./.venv/Scripts/python.exe -m pytest tests/test_member.py -v   # 只跑用户中心
./.venv/Scripts/python.exe -m pytest tests/test_dish.py -v     # 只跑点菜菜单与订单
```

测试使用内存 SQLite（`sqlite:///:memory:`），不会污染 `data/app.db`；
头像写入系统临时目录，验证码不发真实邮件。

| 测试文件 | 覆盖点 |
| --- | --- |
| `tests/test_api.py` | 健康检查、后台登录成功/失败、令牌校验、后台用户增删改查 |
| `tests/test_member.py` | 验证码场景校验与冷却、注册（重复/错误码/弱密码）、**6 位会员编号（格式 / 唯一性 / 后台检索）**、会员登录与刷新、令牌作用域隔离、资料修改、头像上传（含非法文件）、修改密码、验证码重置密码、后台会员管理全流程 |
| `tests/test_dish.py` | 分类/标签 CRUD、标签启用状态（`only_active` 过滤与 C 端隐藏）、菜品与套餐增删改、图片上传、点菜菜单浏览、下单（无套餐/有套餐）、库存与销量联动、起购/限购/每日限量/供应时段校验、取消订单回滚、后台订单状态流转、会员与管理员权限隔离 |

---

## 十三、生产部署

四种方式，按需选择：**13.1 单机** → **13.2 Gunicorn** → **13.3 systemd 常驻** →
**13.4 Nginx 反向代理** → **13.5 Docker（后端容器 + 独立 PG 容器）**。
无论哪种方式，上线前都要：关闭 `DEBUG`、更换 `SECRET_KEY`、把 `DATABASE_URL` 指向正式库。

### 13.1 单机（Windows / Linux 通用）

```powershell
# 必须：关闭 DEBUG、更换 SECRET_KEY、把 DATABASE_URL 指向正式库
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

> `--workers` 与 SQLite 配合不佳，生产建议使用 PostgreSQL / MySQL。

### 13.2 Linux + Gunicorn（推荐）

```bash
pip install "uvicorn[standard]" gunicorn
gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 -b 0.0.0.0:8000 \
  --access-logfile - --error-logfile -
```

### 13.3 systemd 常驻

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

### 13.4 Nginx 反向代理

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

    # 可选：一起托管前端构建产物（前后端同域，可省去跨域配置）
    location / {
        root /var/www/admin;
        try_files $uri $uri/ /index.html;
    }
}
```

### 13.5 Docker 部署（后端容器 + 宿主机上的另一个 PG 容器）

目标形态：**只把后端放进容器，数据库用同宿主机上另一个已有的 PG 容器**
（PG 不在本 compose 内，通过它的宿主机映射端口访问）；**镜像的构建上下文直接从 GitHub 拉取**，
服务器上不需要放源码：

```
https://github.com/duzqiu/fastapi-admin-backend.git
```

| 文件 | 作用 |
| --- | --- |
| `Dockerfile` | 后端镜像：Python 3.13-slim + 依赖 + 非 root 用户 + 健康检查 |
| `docker-compose.yml` | **只有 backend 一个服务**，`build.context` 指向 GitHub 仓库 |
| `.env.docker.example` | compose 变量模板（`cp` 成 `.env`，用于覆盖 PG 连接信息与密钥） |

#### 步骤 0（必须先做）：把 Dockerfile 推送到仓库

`build.context` 是 Git 仓库时，**Dockerfile 必须存在于那个上下文里**，否则构建会直接报
`failed to read dockerfile: ... Dockerfile: not found`。先在本地仓库提交并推送：

```bash
git add Dockerfile .dockerignore docker-compose.yml .env.docker.example .gitignore README.md
git commit -m "add docker deployment"
git push origin main
```

推送后 `docker compose up -d --build` 就会用**最新提交**作为构建上下文。
要固定版本可以写 `context: https://github.com/duzqiu/fastapi-admin-backend.git#v1.0.0`（分支 / 标签 / 提交号都支持）。

#### 步骤 1：确认 PG 容器信息、建好目标库

```bash
# 找到 PG 容器的名字、镜像与端口映射（关注 5452->5432 这一条）
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}"

# 后端只建表、不建库，目标库要事先存在（库名与 .env 里的 PG_DB 保持一致）
docker exec -it <PG容器名> psql -U postgres -c "CREATE DATABASE admin_db;"
```

#### 步骤 2：在服务器上准备 compose 与配置

只需要 `docker-compose.yml` 和 `.env.docker.example` 两个文件，**不用把源码拷过去**：

```bash
mkdir -p /opt/fastapi-admin && cd /opt/fastapi-admin
# 从仓库取这两个文件（git clone 整个仓库、或单独下载这两个文件都行）

cp .env.docker.example .env      # 文件名必须是 .env，compose 才会自动读取
```

数据库相关的默认值已经按「PG 在宿主机、映射端口 5452、用户 postgres」填好，按实际改即可：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PG_HOST` | `host.docker.internal` | 容器里访问宿主机；**不要写 `127.0.0.1`**（那是容器自己） |
| `PG_PORT` | `5452` | 宿主机映射出来的端口（PG 容器自身监听的是 5432） |
| `PG_USER` / `PG_PASSWORD` | `postgres` / `123456` | 按你的实际账号改 |
| `PG_DB` | `admin_db` | 目标库，必须已存在（步骤 1） |

后端会用这些值拼出 `DATABASE_URL`：
`postgresql+psycopg://postgres:123456@host.docker.internal:5452/admin_db`

> 上线前还要改：`SECRET_KEY`（否则任何人都能伪造 JWT）、`BACKEND_CORS_ORIGINS`（前端实际地址）、
> `FIRST_SUPERUSER_PASSWORD`；`DEBUG` 与 `EMAIL_CODE_DEBUG_RETURN` 保持 `false`。

#### 步骤 3：构建并启动

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend
curl http://127.0.0.1:8000/api/v1/system/health
```

首次启动会自动建表并写入初始管理员（`scripts/init_db.py` 幂等，可重复执行）。
如果 PG 还没起来，入口会失败退出，`restart: unless-stopped` 会自动重试。

#### 步骤 4：把本地 SQLite 的数据迁到 PG

应用启动只会**建表**，不会搬数据。PG 端口已映射到宿主机 `5452`，两种方式都行：

```bash
# 方式 A：在宿主机直接跑（需要有项目源码与虚拟环境；源库默认就是 ./data/app.db）
./.venv/Scripts/python.exe scripts/migrate_database.py \
  --target "postgresql+psycopg://postgres:123456@127.0.0.1:5452/admin_db" \
  --create-tables --truncate
```

```bash
# 方式 B：在容器里跑（服务器上没有源码时用这个，把 SQLite 文件挂进去即可）
docker compose run --rm \
  -v "$(pwd)/data:/app/data" \
  backend python scripts/migrate_database.py --create-tables --truncate
```

> Windows PowerShell 把 `$(pwd)` 换成 `${PWD}`。方式 B 里 `--target` 可省略，
> 脚本会自动取容器内的 `DATABASE_URL`。

说明：

- 方式 A 用的是宿主机视角的 `127.0.0.1:5452`，方式 B 用的是容器视角的
  `host.docker.internal:5452`，两者指向同一个 PG；
- `--truncate` 会**按外键逆序**先清空目标表再写入（目标库已有播种数据时正是需要的）；
- 脚本按外键顺序分批拷贝，并对 PostgreSQL 执行 `setval` **重置自增序列**，否则新记录会撞主键；
- 想先确认两边行数是否一致：把 `--create-tables --truncate` 换成 `--verify-only`；
- 跑完执行 `docker compose restart backend`。

#### 步骤 5：常见坑

| 现象 | 原因与处理 |
| --- | --- |
| 构建报 `Dockerfile not found` | 仓库里还没有 `Dockerfile`，先做步骤 0 |
| 构建报拉取 / 认证失败 | 仓库是私有的，需要在 `build.context` 里带凭据或先 `docker login`；公开仓库无此问题 |
| 不支持 Git 作为构建上下文 | 需要 BuildKit（Docker 23+ / Compose v2 默认开启）：`DOCKER_BUILDKIT=1 docker compose build` |
| 服务器拉不动 GitHub | 备选：在服务器上 `git clone` 仓库，把 compose 里的 `context` 改成 `.`（本地目录），效果一样 |
| 连不上数据库（超时） | 主机名写成了 `127.0.0.1`。容器里要用 `host.docker.internal`；Linux 靠 compose 里的 `extra_hosts: host-gateway` 才能解析，容器里可执行 `python -c "import socket;print(socket.gethostbyname('host.docker.internal'))"` 验证 |
| 报 `database "admin_db" does not exist` | 目标库没建，按步骤 1 先 `CREATE DATABASE` |
| 报认证失败 / `password authentication failed` | `PG_USER` / `PG_PASSWORD` 与 PG 实际账号不一致 |
| 后端容器启动即退出 | 入口 `scripts/init_db.py` 连不上库会失败退出；`restart: unless-stopped` 会自动重试，日志搜「数据库初始化失败」 |
| 时段规则不对 | 容器默认 UTC，`TZ` 要设成 `Asia/Shanghai`（影响菜品「供应时段 / 每日限量」） |
| 上传的图片想导出 | 已用命名卷 `uploads` 持久化：`docker cp admin-backend:/app/data/uploads ./` |
| 改了 `.env` 不生效 | 变量只在创建容器时注入，需 `docker compose up -d --force-recreate` |
| 更新到最新代码 | `docker compose up -d --build`（重新拉 GitHub 最新提交，数据卷与表结构不受影响） |

> **更推荐的生产做法（不绕宿主机）**：把两个容器接到同一个自定义网络，用容器名 + 容器内端口直连：
>
> ```bash
> docker network create admin-net
> docker network connect admin-net <PG容器名>       # 把已有 PG 接进来
> ```
>
> 然后 `.env` 里写 `PG_HOST=<PG容器名>`、`PG_PORT=5432`，并给 compose 的 backend 加上：
>
> ```yaml
>     networks: [admin-net]
> # 文件末尾
> networks:
>   admin-net:
>     external: true
> ```
>
> 好处是不经过宿主机端口转发、少一层 NAT，且 PG 端口可以不对宿主机暴露。

> 表名已统一成 `dish_base_* / dish_order_* / member_account_* / system_auth_admin_user`，
> 不含 `user` 这类 PostgreSQL 保留字，建表与查询都不需要额外加双引号。
> 全部 DDL 已用 PostgreSQL 方言预编译校验通过（`SERIAL` / `BOOLEAN` / `TIMESTAMP WITHOUT TIME ZONE` / 外键动作）。

---

## 十四、与前端项目的对接

- 前端项目：`fastapi-admin-frontend`（Vue 3 + Vite + Element Plus），**可独立部署**。
- 通讯方式：仅 HTTP（REST + JSON），后端不渲染任何页面，前端不直连数据库。
- 前端通过 `VITE_API_BASE_URL` 指向本服务的 `/api/v1`。
- 跨域：如果前端与后端**不同域**，必须把前端访问地址加入 `.env` 的 `BACKEND_CORS_ORIGINS`：

```dotenv
BACKEND_CORS_ORIGINS=http://localhost:5173,https://admin.example.com
```

- 认证：前端登录后把 `access_token` 存入本地，之后每个请求带
  `Authorization: Bearer <token>`；收到 401 时用 `refresh_token` 调 `/auth/refresh`，
  失败则跳回登录页。
- 若前后端同域部署（Nginx 同时托管前端静态文件并反代 `/api`），则无需配置跨域。

---

## 附：常见问题

| 问题 | 排查方向 |
| --- | --- |
| 启动报 `database is locked` | SQLite 并发写限制，改用 PostgreSQL/MySQL |
| 前端请求返回 403/被浏览器拦截 | `BACKEND_CORS_ORIGINS` 未包含前端域名 |
| 401 且提示「登录状态已过期」 | access_token 过期，需用 refresh_token 刷新 |
| 迁移后 PG 插入主键冲突 | 已自动 `setval` 重置序列；若手动插过数据需重跑 10.3 节 |
| Docker 里连不上 PG | 容器里不能用 `127.0.0.1`（那是容器自己）；连宿主机上的 PG 用 `host.docker.internal` + 映射端口，或两容器共享自定义网络后用容器名 + 5432，见 13.5 |
| Docker 里报数据库不存在 | 后端只建表不建库，需先 `CREATE DATABASE`，见 13.5 步骤 1 |
| Docker 构建报 `Dockerfile not found` | `build.context` 指向 GitHub 时，Dockerfile 必须先推送到该仓库，见 13.5 步骤 0 |
| Docker 里时段 / 每日限量判断错误 | 容器默认 UTC，需设置 `TZ=Asia/Shanghai` |
| Docker 容器重启后上传的图片丢失 | 上传目录没挂 volume；compose 里已用命名卷 `uploads` 持久化 |
| 密码校验 422 | 密码要求同时包含字母和数字，长度 6–64 |
| 收不到注册验证码 | 未配置 SMTP 时不会真实发信：看响应 `debug_code`，或看服务端日志 `[用户中心] ... code=` |
| 验证码提示「发送过于频繁」 | 同一邮箱 + 场景有 60 秒冷却，可用 `EMAIL_CODE_RESEND_SECONDS=0` 在本地关闭 |
| 提示「令牌使用范围不正确」（40104） | 用了会员令牌访问后台接口（或反之），两套令牌不通用 |
| 图片返回 404 | 确认 `UPLOAD_DIR` 目录存在且可写，并检查 Nginx/代理是否放行了 `/api/v1/static/` |
| 生产环境验证码泄露 | 必须设置 `EMAIL_CODE_DEBUG_RETURN=false` 且 `DEBUG=false` |
| 下单提示「需要选择套餐」 | 该菜品配置了套餐，必须传 `spec_id`；不需要套餐的菜品请勿传该字段 |
| 下单提示「仅在 xx-xx 供应」 | 套餐配置了供应时段，按服务器本地时间判断；留空即为全天供应 |
| 下单提示「今日限量…剩余 N 份」 | 套餐的 `daily_limit` 生效，`sold_today` 在每个本地自然日自动重置 |
| 销售统计与 `sold_count` 不一致 | `sold_count` 是冗余计数；以 `GET /dish-orders/dish-sales`（按明细聚合）为准排查 |
| 取消订单后库存没回来 | 只有「待接单 / 已接单」可取消；「已完成」为终态，需要手工调整库存 |
