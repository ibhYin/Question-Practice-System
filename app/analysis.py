"""知识点引擎：弱点计算、知识点关系图、知识点行动面板数据。

设计核心：把题目、八股卡、作答记录全部挂到「知识点 tag」维度——
- 弱点 = tag 级聚合（不是题目级），换个问法也能被识别
- 知识包 = 系统知识来源（LLM 懒生成，八股卡只是速记锚点）
- 关系图 = tag 共现网络（同题/同卡上的 tag 互为相邻知识）
"""

import json
import time

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from .models import InterviewAnswer, KnowledgePack, Question, StudyCard
from .question_bank import CATEGORY_NAMES
from .redis_client import rdb

WEAKNESS_CACHE_KEY = "weakness:cache"
WEAK_AVG_THRESHOLD = 70  # 平均分低于此判薄弱
DIAG_CACHE_PREFIX = "weakness:diag:"
DIAG_TTL = 86400  # 诊断缓存 1 天


# ---------- 弱点计算 ----------


def compute_weakness(db: DBSession, force: bool = False) -> dict:
    """tag 级弱点聚合。缓存于 Redis，写分数时由 interview 层失效。"""
    if not force:
        cached = rdb.get(WEAKNESS_CACHE_KEY)
        if cached:
            try:
                return json.loads(cached)
            except ValueError:
                pass

    rows = (
        db.query(
            InterviewAnswer.question_id,
            InterviewAnswer.score,
            InterviewAnswer.ai_comment,
            InterviewAnswer.user_answer,
            Question.title,
            Question.category,
            Question.tags,
        )
        .join(Question, Question.id == InterviewAnswer.question_id)
        .filter(InterviewAnswer.score.isnot(None))
        .all()
    )

    # tag -> 聚合
    agg: dict[str, dict] = {}
    for qid, score, comment, user_answer, title, category, tags in rows:
        for tag in tags or []:
            node = agg.setdefault(
                tag, {"tag": tag, "category": category, "attempts": 0, "scores": [], "evidence": []}
            )
            node["attempts"] += 1
            node["scores"].append(score)
            node["evidence"].append(
                {
                    "question_id": qid,
                    "title": title,
                    "score": score,
                    "comment": (comment or "")[:160],
                    "user_answer": (user_answer or "")[:200],
                }
            )

    weak_points = []
    all_points = []
    for node in agg.values():
        scores = node.pop("scores")
        node["avg_score"] = round(sum(scores) / len(scores), 1)
        node["min_score"] = min(scores)
        node["evidence"].sort(key=lambda e: e["score"])  # 最差的排前面
        node["weak"] = node["avg_score"] < WEAK_AVG_THRESHOLD or node["min_score"] < 60
        all_points.append(node)
        if node["weak"]:
            weak_points.append(node)

    weak_points.sort(key=lambda n: (n["avg_score"], -n["attempts"]))
    result = {
        "total_answers": len(rows),
        "total_tags": len(all_points),
        "weak_count": len(weak_points),
        "weak_points": weak_points,
        "all_points": sorted(all_points, key=lambda n: n["avg_score"]),
        "computed_at": time.time(),
    }
    rdb.set(WEAKNESS_CACHE_KEY, json.dumps(result, ensure_ascii=False))
    return result


def invalidate_weakness_cache() -> None:
    rdb.delete(WEAKNESS_CACHE_KEY)
    # 诊断结论跟着作答失效
    for key in rdb.scan_iter("weakness:diag:*"):
        rdb.delete(key)


# ---------- 知识点关系图（tag 共现网络） ----------


def build_tag_graph(db: DBSession, category: str = "") -> dict:
    """知识点关系图：节点 = 题目 tag（带我的掌握状态），边 = 共现。

    节点集合严格限定为真实出现在题目 tags 里的知识点（避免卡片关键点短语
    泛滥成节点）；八股卡只作为共现媒介——卡的 title/points 同时命中两个
    有效 tag 时，为它们补一条弱共现边。
    """
    weakness = compute_weakness(db)
    status_map = {n["tag"]: n for n in weakness["all_points"]}

    questions = db.query(Question).all()
    if category:
        questions = [q for q in questions if q.category == category]
    cards = db.query(StudyCard).all()
    if category:
        cards = [c for c in cards if c.category == category]

    # 有效知识点 = 题目 tags 的并集
    valid_tags: set[str] = set()
    for q in questions:
        valid_tags.update(t for t in (q.tags or []) if t)

    # 题内共现（强边）+ 卡媒介共现（弱边）
    strong: dict[tuple[str, str], int] = {}
    weak: dict[tuple[str, str], int] = {}
    for q in questions:
        tags = sorted({t for t in (q.tags or []) if t})
        for i, a in enumerate(tags):
            for b in tags[i + 1 :]:
                key = (a, b) if a < b else (b, a)
                strong[key] = strong.get(key, 0) + 1
    for c in cards:
        kws = {c.title[:20]} | {p[:20] for p in (c.points or []) if len(p) >= 2}
        kws = [k for k in kws if k in valid_tags]  # 只保留有效 tag
        for i, a in enumerate(kws):
            for b in kws[i + 1 :]:
                key = (a, b) if a < b else (b, a)
                if key in strong:
                    continue  # 已有强边不再补
                weak[key] = weak.get(key, 0) + 1

    nodes: dict[str, dict] = {}
    for t in valid_tags:
        st = status_map.get(t)
        if st and st["weak"]:
            status = "weak"
        elif st:
            status = "encountered"
        else:
            status = "untouched"
        nodes[t] = {
            "name": t,
            "status": status,
            "attempts": st["attempts"] if st else 0,
            "avg_score": st["avg_score"] if st else None,
            "category": st["category"] if st else (questions[0].category if questions else ""),
            "question_count": 0,
        }
    for q in questions:
        for t in q.tags or []:
            if t in nodes:
                nodes[t]["question_count"] += 1

    links = [
        {"source": a, "target": b, "weight": w, "kind": "strong"}
        for (a, b), w in strong.items()
    ] + [
        {"source": a, "target": b, "weight": w, "kind": "weak"}
        for (a, b), w in weak.items()
    ]
    links = [l for l in links if l["source"] in nodes and l["target"] in nodes]
    return {
        "nodes": sorted(nodes.values(), key=lambda n: (-n["question_count"], n["name"])),
        "links": sorted(links, key=lambda l: -l["weight"]),
        "category": category,
    }


# ---------- 知识点行动面板 ----------


def tag_detail(db: DBSession, tag: str) -> dict:
    """一个知识点的完整行动数据：证据 + 关联面试题 + 关联八股卡 + 知识包（若有）"""
    weakness = compute_weakness(db)
    node = next((n for n in weakness["all_points"] if n["tag"] == tag), None)

    # 该 tag 下的面试题（含我的历次作答）
    questions = db.query(Question).filter(Question.tags.contains(tag)).all()
    q_items = []
    for q in questions:
        answers = (
            db.query(InterviewAnswer)
            .filter(InterviewAnswer.question_id == q.id, InterviewAnswer.score.isnot(None))
            .order_by(InterviewAnswer.answered_at.desc())
            .all()
        )
        q_items.append(
            {
                "id": q.id,
                "title": q.title,
                "difficulty": q.difficulty,
                "card_ids": q.card_ids or [],
                "my_attempts": [
                    {"score": a.score, "comment": (a.ai_comment or "")[:160]} for a in answers
                ],
                "model_answer": q.model_answer,
            }
        )

    # 关联八股卡（题的 card_ids 并集 + 标题含 tag 的卡）
    card_ids = set()
    for q in questions:
        card_ids.update(q.card_ids or [])
    extra = db.query(StudyCard).filter(StudyCard.title.contains(tag)).all()
    card_ids.update(c.id for c in extra)
    cards = []
    if card_ids:
        for c in db.query(StudyCard).filter(StudyCard.id.in_(card_ids)).all():
            cards.append(
                {
                    "id": c.id,
                    "title": c.title,
                    "content": c.content,
                    "points": c.points or [],
                    "status": c.status,
                }
            )

    pack = db.query(KnowledgePack).filter(KnowledgePack.tag == tag).first()
    diag = rdb.get(f"{DIAG_CACHE_PREFIX}{tag}")

    return {
        "tag": tag,
        "category": node["category"] if node else (questions[0].category if questions else ""),
        "weak": node["weak"] if node else False,
        "avg_score": node["avg_score"] if node else None,
        "attempts": node["attempts"] if node else 0,
        "evidence": node["evidence"][:5] if node else [],
        "questions": q_items,
        "cards": cards,
        "knowledge_pack": (
            {"content": pack.content, "related_card_ids": pack.related_card_ids}
            if pack
            else None
        ),
        "diagnosis": json.loads(diag) if diag else None,
    }
