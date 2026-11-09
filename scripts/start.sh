#!/usr/bin/env bash
# 启动应用（需先执行过 scripts/setup.sh）
set -e
cd "$(dirname "$0")/.."

# 确保容器引擎在运行。本机引擎为 OrbStack（已替代 Docker Desktop，数据在外置盘）：
# 任意 docker 命令都会自动秒级拉起引擎，这里显式等待就绪即可。
if ! docker info >/dev/null 2>&1; then
    echo "启动容器引擎（OrbStack）..."
    orb start 2>/dev/null || true
    for i in $(seq 1 30); do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 1
    done
fi
docker info >/dev/null 2>&1 || { echo "容器引擎启动失败，请检查 OrbStack"; exit 1; }
docker compose up -d

APP_PORT=$(grep '^APP_PORT=' .env | cut -d= -f2 || echo 8000)

# 端口被占用 = 已有一个应用实例在跑（上次没关/后台残留）——先清掉再启动，避免绑定失败
if lsof -nP -iTCP:"${APP_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 ${APP_PORT} 已被占用（残留实例），先关闭…"
    lsof -nP -tiTCP:"${APP_PORT}" -sTCP:LISTEN | xargs kill 2>/dev/null || true
    sleep 1
fi

echo "启动应用：http://127.0.0.1:${APP_PORT}"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${APP_PORT}"
