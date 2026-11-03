from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..errors import BizError
from ..models import InterviewAnswer, Question
from ..question_bank import CATEGORIES, CATEGORY_NAMES, invalidate_category_cache
from ..schemas import QuestionCreate, QuestionOut, QuestionUpdate

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("")
def list_questions(
    category: str = "",
    difficulty: int = 0,
    source: str = "",
    q: str = "",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    query = db.query(Question)
    if category:
        query = query.filter(Question.category == category)
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)
    if source:
        query = query.filter(Question.source == source)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Question.title.like(like), Question.model_answer.like(like)))
    total = query.count()
    rows = (
        query.order_by(Question.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [QuestionOut.model_validate(r).model_dump() for r in rows],
    }


@router.post("")
def create_question(body: QuestionCreate, db: DBSession = Depends(get_db)):
    if body.category not in CATEGORIES:
        raise BizError(f"category 必须是 {'/'.join(CATEGORIES)} 之一")
    question = Question(
        title=body.title.strip(),
        category=body.category,
        difficulty=body.difficulty,
        tags=body.tags,
        position_tags=body.position_tags,
        source="MANUAL",
        model_answer=body.model_answer.strip(),
    )
    db.add(question)
    db.commit()
    invalidate_category_cache(question.category)
    return QuestionOut.model_validate(question).model_dump()


@router.put("/{qid}")
def update_question(qid: int, body: QuestionUpdate, db: DBSession = Depends(get_db)):
    question = db.get(Question, qid)
    if not question:
        raise BizError("题目不存在", 404)
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in CATEGORIES:
        raise BizError(f"category 必须是 {'/'.join(CATEGORIES)} 之一")
    old_cat = question.category
    for k, v in data.items():
        setattr(question, k, v)
    db.commit()
    invalidate_category_cache(old_cat)
    invalidate_category_cache(question.category)
    return QuestionOut.model_validate(question).model_dump()


@router.delete("/{qid}")
def delete_question(qid: int, db: DBSession = Depends(get_db)):
    question = db.get(Question, qid)
    if not question:
        raise BizError("题目不存在", 404)
    referenced = (
        db.query(InterviewAnswer.id).filter(InterviewAnswer.question_id == qid).first()
    )
    if referenced:
        raise BizError("该题已有作答记录，为保证复盘数据完整，不允许删除")
    db.delete(question)
    db.commit()
    invalidate_category_cache(question.category)
    return {"deleted": qid}


@router.get("/meta")
def meta():
    return {
        "categories": [{"code": c, "name": CATEGORY_NAMES.get(c, c)} for c in CATEGORIES],
    }
