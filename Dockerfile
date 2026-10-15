# 后台接口服务镜像（配合外部 PostgreSQL / MySQL 容器使用）
#
# 构建：docker build -t fastapi-admin-backend:1.0.0 .
# 运行：见 README 第 13.5 节，或直接用同目录的 docker-compose.yml
#
# —— 三个构建参数，专治「网络受限 / 镜像源不可用」，正常网络下无需传参直接用 ——
#   PYTHON_IMAGE   基础镜像。填「完整仓库地址」可绕过 Docker daemon 里失效的加速器：
#                    docker build --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.13-slim .
#   APT_MIRROR     Debian 软件源（装 tzdata 用），默认留空（走镜像自带 deb.debian.org），
#                   可填 https://mirrors.aliyun.com/debian
#   PIP_INDEX_URL  PyPI 源（装 requirements.txt 用），**默认阿里云**
#                    https://mirrors.aliyun.com/pypi/simple/ ；
#                   要换回官方源就显式传 https://pypi.org/simple
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}

# FROM 之后需要重新声明才能在这个阶段里使用
ARG APT_MIRROR=
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    # 容器默认 UTC，会让「菜品供应时段 / 每日限量」按 UTC 判断，这里改成东八区
    TZ=Asia/Shanghai

WORKDIR /app

# tzdata 让上面的 TZ 真正生效（slim 镜像默认不带时区数据）
# 传了 APT_MIRROR 就先替换软件源；Debian 12 用 sources.list、13 用 debian.sources（deb822），两种都覆盖
RUN if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|https\?://deb\.debian\.org/debian|$APT_MIRROR|g" \
        /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# 先装依赖，源码变动时可复用这一层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}" -r requirements.txt

COPY . .

# 上传目录需要可写，且建议挂 volume 持久化
RUN mkdir -p /app/data/uploads \
 && useradd --create-home --shell /bin/bash appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 用 python 探活，省去额外安装 curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/system/health', timeout=4).status == 200 else 1)"

# 先用单进程跑一次初始化（建表 + 初始数据），再启动多进程 uvicorn：
# 应用启动时每个 worker 都会执行一次 init_db()，多进程并发「建表 / 写入初始数据」会互相踩，
# 提前初始化一次后，各 worker 的检查都会直接返回，不再产生写操作。
CMD ["sh", "-c", "python scripts/init_db.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
