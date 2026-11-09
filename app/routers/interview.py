from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .. import interview as interview_svc
from ..database import get_db
from ..errors import BizError
from ..llm import is_enabled
from ..models import InterviewAnswer, InterviewSession, Question
from ..schemas import (
    AnswerDetail,
    AnswerResult,
    AnswerSubmit,
    InterviewStartOut,
    QuestionBrief,
    SessionCreate,
    SessionDetail,
)

router = APIRouter(prefix="/api/interviews", tags=["interview"])


@router.post("", response_model=InterviewStartOut)
def create_interview(body: SessionCreate, db: DBSession = Depends(get_db)):
    result = interview_svc.create_interview(db, body.position.strip(), body.count, body.categories)
    return result


@router.get("")
def list_interviews(limit: int = 20, db: DBSession = Depends(get_db)):
    sessions = (
        db.query(InterviewSession).order_by(InterviewSession.started_at.desc()).limit(limit).all()
    )
    return [
        {
            "id": s.id,
            "position": s.position,
            "mode": s.mode,
            "question_count": s.question_count,
            "status": s.status,
            "total_score": s.total_score,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
        }
        for s in sessions
    ]


@router.get("/{sid}")
def get_interview(sid: int, db: DBSession = Depends(get_db)):
    session = db.get(InterviewSession, sid)
    if not session:
        raise BizError("面试场次不存在", 404)

    qids = session.question_ids or []
    ans_map = {a.question_id: a for a in session.answers}
    # 一次批量取题，避免逐题 N+1
    qmap = {q.id: q for q in db.query(Question).filter(Question.id.in_(qids)).all()} if qids else {}
    answers: list[AnswerDetail] = []
    for idx, qid in enumerate(qids):
        q = qmap.get(qid)
        if not q:
            continue
        a = ans_map.get(qid)
        answers.append(
            AnswerDetail(
                seq=idx + 1,
                question_id=qid,
                question_title=q.title,
                category=q.category,
                difficulty=q.difficulty,
                answered=a is not None,
                user_answer=a.user_answer if a else "",
                # 未作答的题不暴露满分答案（防止先看再答）
                model_answer=a.model_answer if a else "",
                score=a.score if a else None,
                ai_comment=a.ai_comment if a else None,
            )
        )

    return {
        "id": session.id,
        "position": session.position,
        "mode": session.mode,
        "status": session.status,
        "question_count": session.question_count,
        "total_score": session.total_score,
        "summary": session.summary,
        "weak_categories": session.weak_categories,
        "started_at": session.started_at,
        "finished_at": session.finished_at,
        "answers": [a.model_dump() for a in answers],
    }


@router.post("/{sid}/answers", response_model=AnswerResult)
def submit_answer(sid: int, body: AnswerSubmit, db: DBSession = Depends(get_db)):
    result = interview_svc.submit_answer(db, sid, body.question_id, body.user_answer)
    return result


@router.post("/{sid}/finish")
def finish_interview(sid: int, db: DBSession = Depends(get_db)):
    return interview_svc.finish_interview(db, sid)


@router.post("/{sid}/abandon")
def abandon_interview(sid: int, db: DBSession = Depends(get_db)):
    return interview_svc.finish_interview(db, sid, abandoned=True)


@router.get("/{sid}/questions")
def session_questions(sid: int, db: DBSession = Depends(get_db)):
    """本场题目导航列表（题号切换用；不暴露满分答案）"""
    session = db.get(InterviewSession, sid)
    if not session:
        raise BizError("面试场次不存在", 404)
    qids = session.question_ids or []
    ans_map = {a.question_id: a for a in session.answers}
    qmap = {q.id: q for q in db.query(Question).filter(Question.id.in_(qids)).all()} if qids else {}
    items = []
    for idx, qid in enumerate(qids, 1):
        q = qmap.get(qid)
        if not q:
            continue
        a = ans_map.get(qid)
        items.append(
            {
                "id": qid,
                "seq": idx,
                "title": q.title,
                "category": q.category,
                "difficulty": q.difficulty,
                "answered": a is not None,
                "score": a.score if a else None,
            }
        )
    answered_count = sum(1 for i in items if i["answered"])
    return {
        "session_id": sid,
        "status": session.status,
        "mode": session.mode,
        "items": items,
        "answered_count": answered_count,
    }


@router.get("/{sid}/answers/{qid}/score")
def get_answer_score(sid: int, qid: int, db: DBSession = Depends(get_db)):
    """轮询异步评分结果（scoring=true 期间前端每 2s 调一次）"""
    return interview_svc.get_answer_score(db, sid, qid)


@router.get("/{sid}/export")
def export_interview(sid: int, db: DBSession = Depends(get_db)):
    """导出整场复盘为 Markdown 笔记"""
    md = interview_svc.export_markdown(db, sid)
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="interview-{sid}.md"'},
    )


@router.get("/{sid}/progress")
def progress(sid: int, db: DBSession = Depends(get_db)):
    """刷新页面后恢复面试进度用"""
    session = db.get(InterviewSession, sid)
    if not session:
        raise BizError("面试场次不存在", 404)
    if session.status != "in_progress":
        return {"status": session.status, "question": None, "total": session.question_count}
    state = interview_svc.get_state_or_rebuild(db, session)
    question = interview_svc.current_question_brief(db, session, state)
    return {
        "status": "in_progress",
        "question": question,
        "total": session.question_count,
        "current": state["current"],
        "llm_enabled": is_enabled(),
    }
