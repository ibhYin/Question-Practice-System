from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .backup import maybe_backup
from .database import Base, engine
from .errors import BizError
from .llm import is_enabled
from .routers import analysis, interview, questions, review, settings, stats, study, resume
from .redis_client import rdb

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时自动建表（本项目规模不做 migration）
    Base.metadata.create_all(bind=engine)
    # create_all 不改已有表：重答功能需要 attempt_no 列与联合索引，这里幂等补齐
    _migrate_answer_attempts()
    # 智能备份：距上次备份超过 24h 则后台静默备份（用过应用就有新鲜恢复点）
    maybe_backup()
    yield


def _migrate_answer_attempts() -> None:
    """interview_answer 补 attempt_no 列（同场次同题第几次尝试）+ 查询索引，幂等可重复执行。"""
    from sqlalchemy import text

    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE interview_answer ADD COLUMN attempt_no INT NOT NULL DEFAULT 1"
            ))
        except Exception:
            pass  # 列已存在
        try:
            conn.execute(text(
                "CREATE INDEX ix_answer_session_question_attempt "
                "ON interview_answer (session_id, question_id, attempt_no)"
            ))
        except Exception:
            pass  # 索引已存在
        conn.commit()


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
app.include_router(analysis.router)
app.include_router(resume.router)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """开发场景静态资源禁用强缓存：no-cache = 每次向服务器验证（ETag 304 依然高效），
    避免浏览器用旧版 app.js 导致页面空白/功能缺失。"""
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/index.html") or path.startswith(("/app.js", "/style.css")):
        response.headers["Cache-Control"] = "no-cache"
    return response


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
