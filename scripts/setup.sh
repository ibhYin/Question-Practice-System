#!/usr/bin/env bash
# 一键初始化：起 Docker（MySQL+Redis）→ 建表 → 导入内置题库
# 之后用 scripts/start.sh 启动应用
set -e
cd "$(dirname "$0")/.."

echo "==> 1/4 检查 Docker"
if ! docker info >/dev/null 2>&1; then
    echo "    Docker 未运行，正在启动 Docker Desktop..."
    open -a Docker
    for i in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 2
    done
    docker info >/dev/null 2>&1 || { echo "    Docker 启动失败，请手动打开 Docker Desktop"; exit 1; }
fi
echo "    Docker OK"

echo "==> 2/4 启动 MySQL + Redis 容器"
docker compose up -d
echo "    等待 MySQL 就绪..."
for i in $(seq 1 60); do
    if [ "$(docker inspect -f '{{.State.Health.Status}}' interview-mysql 2>/dev/null)" = "healthy" ]; then
        break
    fi
    sleep 2
done
docker inspect -f '{{.State.Health.Status}}' interview-mysql | grep -q healthy || { echo "    MySQL 未就绪"; exit 1; }
echo "    容器 OK"

echo "==> 3/4 安装 Python 依赖"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "    依赖 OK"

echo "==> 4/4 导入内置题库（幂等）"
.venv/bin/python -m seed.load_seed

echo ""
echo "✅ 初始化完成！运行以下命令启动应用："
echo "   ./scripts/start.sh"
echo "   然后浏览器打开 http://127.0.0.1:8010"
