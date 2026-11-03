"""面试流程：创建场次 → 逐题作答 → 结束总评。

Redis 承担：
- HASH interview:session:{id}  进行中场次的当前进度（TTL 2h，丢失可从 DB 重建）
- SETNX interview:lock         同一时间仅允许一场进行中
- ZSET question:hot            高频错题榜
- HASH stats:category          各类别出题数/累计分（cache-aside，可从 MySQL 重建）
"""

import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from . import llm, question_bank, review
from .errors import BizError
from .models import InterviewAnswer, InterviewSession, Question
from .redis_client import rdb

SESSION_TTL = 2 * 3600
LOCK_KEY = "interview:lock"
HOT_KEY = "question:hot"
STATS_KEY = "stats:category"


def _skey(sid: int) -> str:
    return f"interview:session:{sid}"


def _brief(question: Question, seq: int) -> dict:
    return {
        "id": question.id,
        "seq": seq,
        "title": question.title,
        "category": question.category,
        "difficulty": question.difficulty,
        "tags": question.tags or [],
    }


# ---------- 创建 ----------


def create_interview(db: DBSession, position: str, count: int, categories: list[str] | None) -> dict:
    if rdb.exists(LOCK_KEY):
        running_sid = rdb.get(LOCK_KEY)
        raise BizError(f"已有一场进行中的面试（场次 {running_sid}），请先完成或放弃它")

    if categories:
        valid = [c for c in categories if c in question_bank.CATEGORIES]
        if not valid:
            raise BizError("无效的题目类别")
        profile_name, weights = "custom", {c: 1 for c in valid}
    else:
        profile_name, weights = question_bank.match_profile(position)

    picked = question_bank.pick_questions(db, weights, count)
    used_llm = False

    # 题量不足且配置了 LLM：AI 生成新题并入库（source=AI）
    if len(picked) < count and llm.is_enabled():
        need = count - len(picked)
        recent_titles = [
            t
            for (t,) in db.query(Question.title)
            .order_by(Question.id.desc())
            .limit(30)
            .all()
        ]
        try:
            new_qs = llm.generate_questions(
                position,
                list(weights.keys()),
                question_bank.CATEGORY_NAMES,
                need,
                recent_titles,
            )
        except Exception:
            new_qs = []
        for nq in new_qs[:need]:
            title = str(nq.get("title", "")).strip()
            if not title:
                continue
            cat = nq.get("category")
            if cat not in question_bank.CATEGORIES:
                cat = list(weights.keys())[0]
            q = Question(
                title=title,
                category=cat,
                difficulty=int(nq.get("difficulty", 2)),
                tags=nq.get("tags") or [],
                position_tags=[profile_name],
                source="AI",
                model_answer="",
            )
            try:
                q.model_answer = llm.generate_model_answer(q.title, q.category)
            except Exception:
                pass
            db.add(q)
            picked.append(q)
            used_llm = True
        if used_llm:
            db.flush()
            for cat in weights:
                question_bank.invalidate_category_cache(cat)

    if not picked:
        raise BizError("题库中该方向的题目不足，请先在题库管理里录入真题，或在设置中配置 LLM")

    session = InterviewSession(
        position=position,
        question_count=len(picked),
        question_ids=[q.id for q in picked],
        mode="STANDARD",
    )
    db.add(session)
    db.commit()

    _set_state(session.id, 0, session.question_ids)
    rdb.set(LOCK_KEY, str(session.id))

    return {
        "session_id": session.id,
        "position": position,
        "total": len(picked),
        "question": _brief(picked[0], 1),
        "used_llm": used_llm,
    }


# ---------- 进度状态（Redis 为主，DB 兜底重建） ----------


def _set_state(sid: int, current: int, qids: list[int]) -> None:
    rdb.hset(_skey(sid), mapping={"current": current, "question_ids": json.dumps(qids)})
    rdb.expire(_skey(sid), SESSION_TTL)


def _get_state(sid: int) -> dict | None:
    data = rdb.hgetall(_skey(sid))
    if not data:
        return None
    return {"current": int(data.get("current", 0)), "question_ids": json.loads(data.get("question_ids", "[]"))}


def _rebuild_state(db: DBSession, session: InterviewSession) -> dict:
    """Redis 状态丢失（过期/重启）时从数据库重建"""
    qids = session.question_ids or []
    answered = (
        db.query(InterviewAnswer.question_id)
        .filter(InterviewAnswer.session_id == session.id)
        .count()
    )
    state = {"current": min(answered, len(qids)), "question_ids": qids}
    if session.status == "in_progress":
        _set_state(session.id, state["current"], qids)
    return state


# ---------- 答题 ----------


def submit_answer(db: DBSession, sid: int, question_id: int, user_answer: str) -> dict:
    session = db.get(InterviewSession, sid)
    if not session:
        raise BizError("面试场次不存在", 404)
    if session.status != "in_progress":
        raise BizError("该场面试已结束，无法继续作答")

    state = _get_state(sid) or _rebuild_state(db, session)
    qids = state["question_ids"]
    if question_id not in qids:
        raise BizError("该题不属于本场面试")

    question = db.get(Question, question_id)
    if not question:
        raise BizError("题目不存在", 404)

    # 满分答案：题库存的优先，缺了且 LLM 可用则现场生成并回填题库
    model_answer = question.model_answer or ""
    if not model_answer and llm.is_enabled():
        try:
            model_answer = llm.generate_model_answer(question.title, question.category)
            question.model_answer = model_answer
        except Exception:
            model_answer = ""

    # 评分（有 LLM 才有）
    score: int | None = None
    comment: str | None = None
    if llm.is_enabled():
        if not user_answer.strip():
            score, comment = 0, "未作答。这题先记住满分答案的框架，明天复习时再练一遍。"
        else:
            try:
                result = llm.evaluate_answer(question.title, model_answer, user_answer)
                score, comment = result["score"], result["comment"]
            except Exception:
                score, comment = None, None  # LLM 抖动时降级为仅对比模式
    elif not user_answer.strip():
        # 离线模式下直接跳过 = 不会，记 0 分进错题本；作答了则由用户自行复盘
        score, comment = 0, "未作答（离线模式）。先记住满分答案的框架，明天复习时再练。"

    # 落库（同一题重复提交则覆盖）
    ans = (
        db.query(InterviewAnswer)
        .filter(InterviewAnswer.session_id == sid, InterviewAnswer.question_id == question_id)
        .first()
    )
    seq = qids.index(question_id) + 1
    if ans:
        ans.user_answer = user_answer
        ans.model_answer = model_answer
        ans.score = score
        ans.ai_comment = comment
        ans.answered_at = datetime.now()
    else:
        db.add(
            InterviewAnswer(
                session_id=sid,
                question_id=question_id,
                seq=seq,
                user_answer=user_answer,
                model_answer=model_answer,
                score=score,
                ai_comment=comment,
            )
        )
    db.commit()

    # 错题进遗忘曲线队列 + 高频错题榜；类别统计累加
    if score is not None:
        if score < 60:
            review.add_wrong(question_id)
            rdb.zincrby(HOT_KEY, 1, str(question_id))
        cat_key = f"{question.category}:count"
        score_key = f"{question.category}:score"
        rdb.hincrby(STATS_KEY, cat_key, 1)
        if score:
            rdb.hincrby(STATS_KEY, score_key, score)

    # 推进进度
    answered = (
        db.query(func.count(InterviewAnswer.id)).filter(InterviewAnswer.session_id == sid).scalar()
    )
    current = min(answered, len(qids))
    _set_state(sid, current, qids)

    finished = current >= len(qids)
    next_question = _brief(db.get(Question, qids[current]), current + 1) if not finished else None
    return {
        "question_id": question_id,
        "seq": seq,
        "score": score,
        "ai_comment": comment,
        "user_answer": user_answer,
        "model_answer": model_answer,
        "next_question": next_question,
        "finished": finished,
    }


# ---------- 结束 / 放弃 ----------


def finish_interview(db: DBSession, sid: int, abandoned: bool = False) -> dict:
    session = db.get(InterviewSession, sid)
    if not session:
        raise BizError("面试场次不存在", 404)

    if session.status == "in_progress":
        answers = (
            db.query(InterviewAnswer)
            .filter(InterviewAnswer.session_id == sid)
            .order_by(InterviewAnswer.seq)
            .all()
        )
        scored = [a for a in answers if a.score is not None]
        weak: list[str] = []
        if scored:
            session.total_score = round(sum(a.score for a in scored) / len(scored), 1)
            per_cat: dict[str, list[int]] = {}
            for a in scored:
                per_cat.setdefault(a.question.category, []).append(a.score)
            weak = [c for c, ss in per_cat.items() if sum(ss) / len(ss) < 60]
            session.weak_categories = weak or None

        if not abandoned and scored and llm.is_enabled():
            try:
                session.summary = llm.summarize_session(
                    session.position,
                    [
                        {
                            "title": a.question.title,
                            "category": a.question.category,
                            "score": a.score,
                            "comment": a.ai_comment or "",
                        }
                        for a in scored
                    ],
                )
            except Exception:
                pass
        if not session.summary:
            if weak:
                names = "、".join(question_bank.CATEGORY_NAMES.get(c, c) for c in weak)
                session.summary = f"薄弱方向：{names}。建议把本场错题加入复习计划，一周后再来一场同岗位面试验证。"
            elif abandoned:
                session.summary = "本场已放弃，未生成总评。"
            else:
                session.summary = "本场未产生评分数据（离线模式不评分），请对照满分答案自行复盘。"

        session.status = "abandoned" if abandoned else "finished"
        session.finished_at = datetime.now()
        db.commit()

    # 释放会话状态与全场锁
    rdb.delete(_skey(sid))
    if rdb.get(LOCK_KEY) == str(sid):
        rdb.delete(LOCK_KEY)
    return {"session_id": sid, "status": session.status}


def get_state_or_rebuild(db: DBSession, session: InterviewSession) -> dict:
    return _get_state(session.id) or _rebuild_state(db, session)


def current_question_brief(db: DBSession, session: InterviewSession, state: dict) -> dict | None:
    qids = state["question_ids"]
    current = state["current"]
    if current >= len(qids):
        return None
    q = db.get(Question, qids[current])
    return _brief(q, current + 1) if q else None


# ---------- 统计（Redis HASH 缓存，miss 时从 MySQL 重建） ----------


def category_stats(db: DBSession) -> list[dict]:
    data = rdb.hgetall(STATS_KEY)
    if not data:
        rows = (
            db.query(
                Question.category,
                func.count(InterviewAnswer.id),
                func.avg(InterviewAnswer.score),
            )
            .join(InterviewAnswer, InterviewAnswer.question_id == Question.id)
            .group_by(Question.category)
            .all()
        )
        if rows:
            pipe = rdb.pipeline()
            for cat, cnt, avg in rows:
                pipe.hset(STATS_KEY, f"{cat}:count", cnt)
                if avg is not None:
                    pipe.hset(STATS_KEY, f"{cat}:score", round(float(avg) * cnt))
            pipe.expire(STATS_KEY, 600)
            pipe.execute()
            data = rdb.hgetall(STATS_KEY)

    result = []
    for cat in question_bank.CATEGORIES:
        cnt = int(data.get(f"{cat}:count", 0))
        if cnt:
            total_score = int(data.get(f"{cat}:score", 0))
            result.append(
                {
                    "category": cat,
                    "name": question_bank.CATEGORY_NAMES.get(cat, cat),
                    "count": cnt,
                    "avg_score": round(total_score / cnt, 1),
                }
            )
    return result


def hot_questions(db: DBSession, limit: int = 10) -> list[dict]:
    items = rdb.zrevrange(HOT_KEY, 0, limit - 1, withscores=True)
    out = []
    for qid, wrong_count in items:
        q = db.get(Question, int(qid))
        if q:
            out.append({"id": q.id, "title": q.title, "category": q.category, "wrong_count": int(wrong_count)})
    return out


def session_started_at(session: InterviewSession) -> str:
    return session.started_at.isoformat() if session.started_at else ""
