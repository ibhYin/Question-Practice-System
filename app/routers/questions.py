from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from .. import interview as interview_svc
from .. import review as review_svc
from ..backup import maybe_backup
from ..database import get_db
from ..errors import BizError
from ..models import InterviewAnswer, Question, StudyCard
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


@router.get("/{qid}/framework")
def get_framework(qid: int, db: DBSession = Depends(get_db)):
    """读取本题知识框架（未生成则返回 null，前端提示可生成）"""
    q = db.get(Question, qid)
    if not q:
        raise BizError("题目不存在", 404)
    return {"question_id": qid, "framework": q.framework or None}


@router.post("/{qid}/framework")
def gen_framework(qid: int, db: DBSession = Depends(get_db)):
    """懒生成本题知识框架（前置→骨架→易错→延伸 的树状大纲），生成后缓存"""
    from .. import llm
    from ..analysis import compute_weakness

    q = db.get(Question, qid)
    if not q:
        raise BizError("题目不存在", 404)
    if q.framework:
        return {"question_id": qid, "framework": q.framework, "cached": True}
    if not llm.is_enabled():
        raise BizError("知识框架生成需要先在设置中配置 LLM")

    # 该题的历史作答作为证据（弱项针对性）
    weakness = compute_weakness(db)
    node = next((n for n in weakness["all_points"] if n["tag"] in (q.tags or [])), None)
    evidence = node["evidence"][:3] if node else []

    try:
        fw = llm.generate_framework(q.title, q.model_answer, evidence, q.tags)
    except Exception as e:
        raise BizError(f"知识框架生成失败：{type(e).__name__}，请稍后重试")
    if not fw:
        raise BizError("知识框架生成为空，请重试")
    q.framework = fw
    db.commit()
    return {"question_id": qid, "framework": fw, "cached": False}


@router.get("/{qid}/cards")
def question_cards(qid: int, db: DBSession = Depends(get_db)):
    """该题关联的八股知识点卡（答题结果页展示"背哪几张卡能答好这类题"）"""
    q = db.get(Question, qid)
    if not q:
        raise BizError("题目不存在", 404)
    card_ids = q.card_ids or []
    cards = []
    if card_ids:
        rows = db.query(StudyCard).filter(StudyCard.id.in_(card_ids)).all()
        by_id = {c.id: c for c in rows}
        # 按 card_ids 顺序输出（建链时按相关度排序）
        for cid in card_ids:
            c = by_id.get(cid)
            if c:
                cards.append(
                    {
                        "id": c.id,
                        "title": c.title,
                        "content": c.content,
                        "points": c.points or [],
                        "status": c.status,
                        "category_name": CATEGORY_NAMES.get(c.category, c.category),
                    }
                )
    return {"question_id": qid, "title": q.title, "cards": cards}


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
