#!/usr/bin/env bash
# 启动应用（需先执行过 scripts/setup.sh）
set -e
cd "$(dirname "$0")/.."

# 确保 MySQL/Redis 在运行
if ! docker info >/dev/null 2>&1; then
    echo "Docker 未运行，正在启动..."
    open -a Docker
    for i in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 2
    done
fi
docker compose up -d

APP_PORT=$(grep '^APP_PORT=' .env | cut -d= -f2 || echo 8000)
echo "启动应用：http://127.0.0.1:${APP_PORT}"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${APP_PORT}"
