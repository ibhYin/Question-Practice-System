from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from .. import review as review_svc
from ..database import get_db
from ..errors import BizError
from ..models import Question
from ..question_bank import CATEGORY_NAMES
from ..redis_client import rdb
from ..schemas import ReviewAnswerIn

router = APIRouter(prefix="/api/review", tags=["review"])


def _to_item(db: DBSession, qid: int, stage: int | None = None) -> dict | None:
    q = db.get(Question, qid)
    if not q:
        return None
    return {
        "id": q.id,
        "title": q.title,
        "category": q.category,
        "category_name": CATEGORY_NAMES.get(q.category, q.category),
        "difficulty": q.difficulty,
        "tags": q.tags or [],
        "stage": stage if stage is not None else review_svc.stage_of(qid),
    }


@router.get("/due")
def due_questions(db: DBSession = Depends(get_db)):
    """到期待复习的错题"""
    items = []
    for qid in review_svc.due_ids():
        item = _to_item(db, qid)
        if item:
            items.append(item)
    return {"due_count": len(items), "queue_size": review_svc.queue_size(), "items": items}


@router.get("/upcoming")
def upcoming_questions(db: DBSession = Depends(get_db)):
    """未到期、最近将到期的错题（预习提示）"""
    items = []
    for qid in review_svc.upcoming_ids():
        item = _to_item(db, qid)
        if item:
            items.append(item)
    return {"items": items}


@router.post("/{qid}/add")
def add_to_review(qid: int, db: DBSession = Depends(get_db)):
    """手动把题目加入复习队列（离线自查后觉得没掌握时用）"""
    q = db.get(Question, qid)
    if not q:
        raise BizError("题目不存在", 404)
    review_svc.add_wrong(qid)
    return {"added": qid, "next_interval_days": review_svc.INTERVALS_DAYS[0]}


@router.post("/{qid}/answer")
def answer_review(qid: int, body: ReviewAnswerIn, db: DBSession = Depends(get_db)):
    q = db.get(Question, qid)
    if not q:
        raise BizError("题目不存在", 404)
    if rdb.zscore(review_svc.REVIEW_QUEUE, str(qid)) is None:
        raise BizError("该题不在错题队列中")
    return review_svc.answer_review(qid, body.correct)
