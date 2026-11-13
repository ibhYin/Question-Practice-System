"""简历面试模块：上传/解析简历 → LLM 按简历生成深挖题（RESUME 类别）→ 复用面试流程。"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..errors import BizError
from ..llm import generate_resume_questions, is_enabled
from ..models import Question, Resume
from ..question_bank import invalidate_category_cache
from ..backup import maybe_backup

router = APIRouter(prefix="/api/resume", tags=["resume"])

RESUME_CATEGORY = "RESUME"


def _resume_out(r: Resume) -> dict:
    return {
        "id": r.id,
        "filename": r.filename,
        "char_count": r.char_count,
        "is_active": r.is_active,
        "created_at": r.created_at,
    }


def _get_active_resume(db: DBSession) -> Resume:
    r = db.query(Resume).filter(Resume.is_active.is_(True)).order_by(Resume.id.desc()).first()
    if not r:
        raise BizError("请先上传简历", 404)
    return r


@router.post("/upload")
async def upload_resume(file: UploadFile | None = File(None), db: DBSession = Depends(get_db)):
    """上传简历文件（pdf/txt/md）或前端直接传纯文本。落库为新版本并激活。"""
    import io

    from pypdf import PdfReader

    filename = (file.filename or "resume.txt") if file else "粘贴文本"
    if file:
        data = await file.read()
        suffix = (filename or "").lower().rsplit(".", 1)[-1]
        if suffix == "pdf":
            try:
                reader = PdfReader(stream=io.BytesIO(data), strict=False)
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception:
                raise BizError("PDF 解析失败，请确认文件完整")
            if not text.strip():
                raise BizError("未从 PDF 抽取到文本（疑似扫描件），请改用文本粘贴")
        else:
            text = data.decode("utf-8", errors="replace")
    else:
        raise BizError("缺少文件")

    text = text.strip()
    if len(text) < 100:
        raise BizError(f"简历文本过短（{len(text)} 字符），请检查文件内容")

    # 新版本激活，旧版本全部取消激活
    db.query(Resume).update({Resume.is_active: False})
    r = Resume(filename=filename, content=text, char_count=len(text), is_active=True)
    db.add(r)
    db.commit()
    return _resume_out(r)


@router.post("/paste")
def paste_resume(body: dict, db: DBSession = Depends(get_db)):
    """纯文本粘贴通道（不依赖文件）。"""
    text = str(body.get("content", "")).strip()
    filename = str(body.get("filename", "")).strip() or "粘贴文本"
    if len(text) < 100:
        raise BizError(f"简历文本过短（{len(text)} 字符），请粘贴完整简历")
    db.query(Resume).update({Resume.is_active: False})
    r = Resume(filename=filename, content=text, char_count=len(text), is_active=True)
    db.add(r)
    db.commit()
    return _resume_out(r)


@router.get("")
def list_resumes(db: DBSession = Depends(get_db)):
    versions = db.query(Resume).order_by(Resume.id.desc()).all()
    pool = (
        db.query(func.count(Question.id))
        .filter(Question.category == RESUME_CATEGORY)
        .scalar()
        or 0
    )
    return {"versions": [_resume_out(r) for r in versions], "question_count": pool}


@router.post("/{rid}/activate")
def activate_resume(rid: int, db: DBSession = Depends(get_db)):
    r = db.get(Resume, rid)
    if not r:
        raise BizError("简历版本不存在", 404)
    db.query(Resume).update({Resume.is_active: False})
    r.is_active = True
    db.commit()
    return _resume_out(r)


@router.delete("/{rid}")
def delete_resume(rid: int, db: DBSession = Depends(get_db)):
    r = db.get(Resume, rid)
    if not r:
        raise BizError("简历版本不存在", 404)
    db.delete(r)
    # 若删掉了激活版本，把最新一条顶上
    latest = db.query(Resume).order_by(Resume.id.desc()).first()
    if latest and not db.query(Resume).filter(Resume.is_active.is_(True)).first():
        latest.is_active = True
    db.commit()
    return {"ok": True}


@router.post("/generate-questions")
def generate_questions_from_resume(
    body: dict,
    db: DBSession = Depends(get_db),
):
    """基于激活简历生成 N 道深挖题（RESUME 类别，source=RESUME，含建议回答）。"""
    if not is_enabled():
        raise BizError("简历出题需要先在「设置」中配置 LLM")
    try:
        count = int(body.get("count", 8))
    except (TypeError, ValueError):
        count = 8
    count = max(1, min(15, count))

    r = _get_active_resume(db)

    avoid = [
        t
        for (t,) in db.query(Question.title)
        .filter(Question.category == RESUME_CATEGORY)
        .all()
    ]
    try:
        new_qs = generate_resume_questions(r.content, count, avoid)
    except Exception as e:
        raise BizError(f"出题失败：{type(e).__name__}，请稍后重试")
    if not new_qs:
        raise BizError("LLM 未返回有效题目，请重试")

    added, skipped = 0, 0
    existing = set(avoid)
    for nq in new_qs[:count]:
        title = str(nq.get("title", "")).strip()
        if not title or title in existing:
            skipped += 1
            continue
        existing.add(title)
        db.add(
            Question(
                title=title,
                category=RESUME_CATEGORY,
                difficulty=max(1, min(3, int(nq.get("difficulty", 2) or 2))),
                tags=nq.get("tags") or [],
                position_tags=["resume"],
                source="RESUME",
                model_answer=str(nq.get("answer", "")).strip(),
            )
        )
        added += 1
    db.commit()
    if added:
        invalidate_category_cache(RESUME_CATEGORY)
        maybe_backup()

    pool = (
        db.query(func.count(Question.id))
        .filter(Question.category == RESUME_CATEGORY)
        .scalar()
        or 0
    )
    return {"added": added, "skipped": skipped, "question_count": pool}
