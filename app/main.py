from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .backup import maybe_backup
from .database import Base, engine
from .errors import BizError
from .llm import is_enabled
from .routers import interview, questions, review, settings, stats, study
from .redis_client import rdb

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时自动建表（本项目规模不做 migration）
    Base.metadata.create_all(bind=engine)
    # 智能备份：距上次备份超过 24h 则后台静默备份（用过应用就有新鲜恢复点）
    maybe_backup()
    yield


app = FastAPI(title="面试刷题系统", version="1.0.0", lifespan=lifespan)


@app.exception_handler(BizError)
def biz_error_handler(_req: Request, exc: BizError):
    return JSONResponse(status_code=exc.code, content={"detail": exc.message})


app.include_router(interview.router)
app.include_router(questions.router)
app.include_router(review.router)
app.include_router(stats.router)
app.include_router(settings.router)
app.include_router(study.router)


@app.get("/api/health")
def health():
    status = {"mysql": "ok", "redis": "ok", "llm": "on" if is_enabled() else "off"}
    code = 200
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        status["mysql"] = "down"
        code = 503
    try:
        rdb.ping()
    except Exception:
        status["redis"] = "down"
        code = 503
    return JSONResponse(status_code=code, content=status)


# 静态页面放最后挂载，避免吞掉 /api 路由
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
