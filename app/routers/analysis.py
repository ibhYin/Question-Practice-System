"""知识点掌握路由：弱点诊断 / 知识点关系图 / 变体训练 / 知识包。"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .. import analysis, llm, question_bank
from ..database import get_db
from ..errors import BizError
from ..models import InterviewSession, KnowledgePack, Question
from ..question_bank import CATEGORY_NAMES

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/weakness")
def weakness(db: DBSession = Depends(get_db)):
    """知识点级弱点列表（含证据），按严重度排序"""
    result = analysis.compute_weakness(db)
    return {
        "total_answers": result["total_answers"],
        "total_tags": result["total_tags"],
        "weak_count": result["weak_count"],
        "weak_points": result["weak_points"][:20],
        "all_points": result["all_points"][:30],
    }


@router.get("/knowledge-graph")
def knowledge_graph(category: str = "", db: DBSession = Depends(get_db)):
    """知识点关系图：节点 = tag（我的掌握状态着色），边 = 共现"""
    return analysis.build_tag_graph(db, category)


@router.get("/tags/{tag}/detail")
def tag_detail(tag: str, db: DBSession = Depends(get_db)):
    """知识点行动面板：证据 + 关联题 + 关联卡 + 知识包 + 诊断（如有）"""
    return analysis.tag_detail(db, tag)


@router.post("/diagnose")
def diagnose(body: dict, db: DBSession = Depends(get_db)):
    """LLM 深度诊断该知识点的具体欠缺（基于真实作答，结果缓存）"""
    tag = str(body.get("tag", "")).strip()
    if not tag:
        raise BizError("tag 不能为空")
    detail = analysis.tag_detail(db, tag)
    if not detail["evidence"]:
        raise BizError("该知识点还没有作答记录，先去刷几题再来诊断")
    try:
        diag = llm.diagnose_tag(tag, detail["category"], detail["evidence"])
    except Exception as e:
        raise BizError(f"诊断失败：{type(e).__name__}，请稍后重试")
    from ..redis_client import rdb
    import json as _json

    rdb.setex(f"{analysis.DIAG_CACHE_PREFIX}{tag}", analysis.DIAG_TTL, _json.dumps(diag, ensure_ascii=False))
    return diag


@router.post("/knowledge-pack")
def knowledge_pack(body: dict, db: DBSession = Depends(get_db)):
    """获取（或懒生成）知识点的系统知识包——完整知识来源，非速记卡"""
    tag = str(body.get("tag", "")).strip()
    if not tag:
        raise BizError("tag 不能为空")

    pack = db.query(KnowledgePack).filter(KnowledgePack.tag == tag).first()
    if pack:
        return _pack_response(db, pack)

    detail = analysis.tag_detail(db, tag)
    category = detail["category"] or "SCENARIO"
    evidence = [
        {"title": e["title"], "user_answer": e["user_answer"], "score": e["score"], "comment": e["comment"]}
        for e in detail["evidence"]
    ]
    try:
        result = llm.generate_knowledge_pack(tag, CATEGORY_NAMES.get(category, category), evidence)
    except Exception as e:
        raise BizError(f"知识包生成失败：{type(e).__name__}，请稍后重试")

    content = result["content"]
    if not content:
        raise BizError("知识包生成内容为空，请重试")

    pack = KnowledgePack(
        tag=tag,
        category=category,
        content=content,
        related_card_ids=[c["id"] for c in detail["cards"]],
        related_question_ids=[q["id"] for q in detail["questions"]],
        source="AI",
    )
    db.add(pack)
    db.commit()

    resp = _pack_response(db, pack)
    # 变体题一并返回（前端可选开练）
    resp["variant_questions"] = result.get("variant_questions", [])
    return resp


def _pack_response(db: DBSession, pack: KnowledgePack) -> dict:
    return {
        "tag": pack.tag,
        "category": pack.category,
        "content": pack.content,
        "related_card_ids": pack.related_card_ids or [],
        "related_question_ids": pack.related_question_ids or [],
    }


@router.post("/variant-session")
def variant_session(body: dict, db: DBSession = Depends(get_db)):
    """为薄弱知识点生成变体题专项训练场次（换汤不换药识别训练）"""
    tag = str(body.get("tag", "")).strip()
    count = int(body.get("count", 4))
    if not tag:
        raise BizError("tag 不能为空")
    count = max(2, min(count, 6))

    # 已有变体题直接复用（同 tag、source=AI），不足再生成
    existing = (
        db.query(Question)
        .filter(Question.tags.contains(tag), Question.source == "AI")
        .order_by(Question.id.desc())
        .limit(count)
        .all()
    )
    picked = list(existing)
    if len(picked) < count:
        base_titles = [
            t
            for (t,) in db.query(Question.title)
            .filter(Question.tags.contains(tag))
            .limit(10)
            .all()
        ]
        category = (
            db.query(Question.category).filter(Question.tags.contains(tag)).first()
        )
        category = category[0] if category else "SCENARIO"
        try:
            variants = llm.generate_variants(
                tag, CATEGORY_NAMES.get(category, category), base_titles, count - len(picked)
            )
        except Exception as e:
            raise BizError(f"变体题生成失败：{type(e).__name__}，请稍后重试")
        for v in variants:
            title = str(v.get("title", "")).strip()
            if not title:
                continue
            db.add(
                Question(
                    title=title,
                    category=category,
                    difficulty=int(v.get("difficulty", 2)),
                    tags=[tag] + [t for t in v.get("tags", []) if t != tag][:3],
                    position_tags=[],
                    source="AI",
                    model_answer="",  # 答题时按需生成
                )
            )
        db.flush()
        new_qs = (
            db.query(Question)
            .filter(Question.tags.contains(tag), Question.source == "AI")
            .order_by(Question.id.desc())
            .limit(count)
            .all()
        )
        picked = new_qs[:count]
        question_bank.invalidate_category_cache(category)

    if not picked:
        raise BizError("变体题生成结果为空，请重试")

    session = InterviewSession(
        position=f"变体训练 · {tag}",
        mode="STANDARD",
        question_count=len(picked),
        question_ids=[q.id for q in picked],
    )
    db.add(session)
    db.commit()

    from .. import interview as interview_svc

    interview_svc._set_state(session.id, 0, session.question_ids)
    from ..redis_client import rdb as _rdb

    _rdb.set(interview_svc.LOCK_KEY, str(session.id), ex=interview_svc.LOCK_TTL)

    first = picked[0]
    return {
        "session_id": session.id,
        "tag": tag,
        "total": len(picked),
        "question": {
            "id": first.id,
            "seq": 1,
            "title": first.title,
            "category": first.category,
            "difficulty": first.difficulty,
            "tags": first.tags or [],
        },
    }
