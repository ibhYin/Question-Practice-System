from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .. import interview as interview_svc
from .. import review as review_svc
from ..database import get_db
from ..models import InterviewSession, Question

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def stats(db: DBSession = Depends(get_db)):
    total_questions = db.query(func.count(Question.id)).scalar() or 0
    session_count = db.query(func.count(InterviewSession.id)).scalar() or 0
    answered_count = (
        db.query(func.count(InterviewSession.id))
        .filter(InterviewSession.status == "finished")
        .scalar()
        or 0
    )
    return {
        "total_questions": total_questions,
        "session_count": session_count,
        "finished_sessions": answered_count,
        "due_count": review_svc.due_count(),
        "queue_size": review_svc.queue_size(),
        "categories": interview_svc.category_stats(db),
        "hot": interview_svc.hot_questions(db, limit=10),
    }
