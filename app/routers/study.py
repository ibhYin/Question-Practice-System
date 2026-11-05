"""八股文库路由：背诵卡片 + 体系长文档（与面试题库完全分离）。"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..errors import BizError
from ..models import StudyCard, StudyDoc
from ..question_bank import CATEGORY_NAMES

router = APIRouter(prefix="/api/study", tags=["study"])


class CardStatusIn(BaseModel):
    status: str  # new / learning / mastered


@router.get("/overview")
def overview(db: DBSession = Depends(get_db)):
    """各类别文档数/卡片数/背诵进度汇总"""
    docs = dict(
        db.query(StudyDoc.category, func.count(StudyDoc.id))
        .group_by(StudyDoc.category)
        .all()
    )
    card_rows = (
        db.query(StudyCard.category, StudyCard.status, func.count(StudyCard.id))
        .group_by(StudyCard.category, StudyCard.status)
        .all()
    )
    card_counts: dict[str, dict[str, int]] = {}
    for cat, status, cnt in card_rows:
        card_counts.setdefault(cat, {})[status] = cnt

    result = []
    for cat in CATEGORY_NAMES:
        cc = card_counts.get(cat, {})
        total = sum(cc.values())
        mastered = cc.get("mastered", 0)
        if total == 0 and cat not in docs:
            continue
        result.append(
            {
                "category": cat,
                "name": CATEGORY_NAMES.get(cat, cat),
                "docs": docs.get(cat, 0),
                "cards": total,
                "mastered": mastered,
                "learning": cc.get("learning", 0),
                "new": cc.get("new", 0),
                "progress": round(mastered / total * 100) if total else 0,
            }
        )
    return result


@router.get("/docs")
def list_docs(category: str = "", db: DBSession = Depends(get_db)):
    query = db.query(StudyDoc)
    if category:
        query = query.filter(StudyDoc.category == category)
    rows = query.order_by(StudyDoc.category, StudyDoc.id).all()
    return [
        {
            "id": d.id,
            "category": d.category,
            "category_name": CATEGORY_NAMES.get(d.category, d.category),
            "title": d.title,
        }
        for d in rows
    ]


@router.get("/docs/{doc_id}")
def get_doc(doc_id: int, db: DBSession = Depends(get_db)):
    doc = db.get(StudyDoc, doc_id)
    if not doc:
        raise BizError("文档不存在", 404)
    return {
        "id": doc.id,
        "category": doc.category,
        "category_name": CATEGORY_NAMES.get(doc.category, doc.category),
        "title": doc.title,
        "content": doc.content,
    }


@router.get("/cards")
def list_cards(
    category: str = "",
    status: str = "",
    db: DBSession = Depends(get_db),
):
    query = db.query(StudyCard)
    if category:
        query = query.filter(StudyCard.category == category)
    if status:
        query = query.filter(StudyCard.status == status)
    rows = query.order_by(StudyCard.category, StudyCard.id).all()
    return [
        {
            "id": c.id,
            "category": c.category,
            "category_name": CATEGORY_NAMES.get(c.category, c.category),
            "title": c.title,
            "content": c.content,
            "points": c.points or [],
            "status": c.status,
        }
        for c in rows
    ]


@router.post("/cards/{card_id}/status")
def set_card_status(card_id: int, body: CardStatusIn, db: DBSession = Depends(get_db)):
    if body.status not in ("new", "learning", "mastered"):
        raise BizError("status 必须是 new/learning/mastered")
    card = db.get(StudyCard, card_id)
    if not card:
        raise BizError("卡片不存在", 404)
    card.status = body.status
    db.commit()
    return {"id": card.id, "status": card.status}
