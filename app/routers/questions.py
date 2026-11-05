from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from .. import interview as interview_svc
from .. import review as review_svc
from ..backup import maybe_backup
from ..database import get_db
from ..errors import BizError
from ..models import InterviewAnswer, Question
from ..question_bank import CATEGORIES, CATEGORY_NAMES, invalidate_category_cache
from ..redis_client import rdb
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
    maybe_backup()  # 录入真题 = 高价值数据变化
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
    # 同步清理 Redis 中的残留（复习队列/阶段/高频错题榜）
    rdb.zrem(review_svc.REVIEW_QUEUE, str(qid))
    rdb.hdel(review_svc.REVIEW_STAGE, str(qid))
    rdb.zrem(interview_svc.HOT_KEY, str(qid))
    invalidate_category_cache(question.category)
    maybe_backup()
    return {"deleted": qid}


@router.get("/meta")
def meta():
    return {
        "categories": [{"code": c, "name": CATEGORY_NAMES.get(c, c)} for c in CATEGORIES],
    }


# ---------- 知识地图 ----------


@router.get("/knowledge/map")
def knowledge_map(category: str = "", db: DBSession = Depends(get_db)):
    """类别考点关联图：节点 = 题目，边 = related_ids 关联对"""
    query = db.query(Question)
    if category:
        query = query.filter(Question.category == category)
    questions = query.all()
    hot = {int(k): int(v) for k, v in rdb.zrange(interview_svc.HOT_KEY, 0, -1, withscores=True)}
    nodes = [
        {
            "id": q.id,
            "name": q.title[:24],
            "category": q.category,
            "difficulty": q.difficulty,
            "wrong_count": hot.get(q.id, 0),  # 节点大小/红色标记依据
        }
        for q in questions
    ]
    idset = {q.id for q in questions}
    links = []
    for q in questions:
        for rid in q.related_ids or []:
            if rid in idset and rid > q.id:  # 去重：只输出一次边
                links.append({"source": q.id, "target": rid})
    return {"nodes": nodes, "links": links, "categories": sorted({q.category for q in questions})}


@router.get("/knowledge/{qid}")
def knowledge_chain(qid: int, db: DBSession = Depends(get_db)):
    """单题知识链路：关联题列表（点击后可看满分答案）"""
    q = db.get(Question, qid)
    if not q:
        raise BizError("题目不存在", 404)
    rels = q.related_ids or []
    items = []
    if rels:
        for r in db.query(Question).filter(Question.id.in_(rels)).all():
            items.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "category": r.category,
                    "category_name": CATEGORY_NAMES.get(r.category, r.category),
                    "difficulty": r.difficulty,
                    "tags": r.tags or [],
                    "model_answer": r.model_answer,
                }
            )
    items.sort(key=lambda x: (x["category"], x["id"]))
    return {
        "question_id": qid,
        "related": items,
        "category_name": CATEGORY_NAMES.get(q.category, q.category),
    }
