"""错题复习：基于 Redis ZSET 的遗忘曲线队列。

member = question_id(str)，score = 下次应复习的时间戳。
间隔阶梯 [1, 3, 7, 14] 天，复习答对进入下一阶，答错回到第 0 阶；
走完阶梯即"已掌握"，移出队列。
"""

import time

from .redis_client import rdb

REVIEW_QUEUE = "review:queue"  # ZSET
REVIEW_STAGE = "review:stage"  # HASH: qid -> 当前阶段(0 起)
INTERVALS_DAYS = [1, 3, 7, 14]


def _ts_now() -> float:
    return time.time()


def add_wrong(question_id: int) -> None:
    """答错/新错题：进入或重置到第 0 阶，明天再练"""
    qid = str(question_id)
    rdb.hset(REVIEW_STAGE, qid, 0)
    rdb.zadd(REVIEW_QUEUE, {qid: _ts_now() + INTERVALS_DAYS[0] * 86400})


def answer_review(question_id: int, correct: bool) -> dict:
    """复习后更新队列，返回 {mastered, next_interval_days}"""
    qid = str(question_id)
    if correct:
        stage = int(rdb.hget(REVIEW_STAGE, qid) or 0) + 1
        if stage >= len(INTERVALS_DAYS):
            # 走完阶梯：已掌握
            rdb.hdel(REVIEW_STAGE, qid)
            rdb.zrem(REVIEW_QUEUE, qid)
            return {"mastered": True, "next_interval_days": None}
        rdb.hset(REVIEW_STAGE, qid, stage)
        days = INTERVALS_DAYS[stage]
        rdb.zadd(REVIEW_QUEUE, {qid: _ts_now() + days * 86400})
        return {"mastered": False, "next_interval_days": days}
    # 答错：重置
    return {**add_wrong_result(question_id), "mastered": False}


def add_wrong_result(question_id: int) -> dict:
    add_wrong(question_id)
    return {"next_interval_days": INTERVALS_DAYS[0]}


def due_ids() -> list[int]:
    """到期待复习的题目 id"""
    return [int(x) for x in rdb.zrangebyscore(REVIEW_QUEUE, "-inf", _ts_now())]


def upcoming_ids(limit: int = 20) -> list[int]:
    """尚未到期、最近将到期的题目 id"""
    return [int(x) for x in rdb.zrangebyscore(REVIEW_QUEUE, f"({_ts_now()}", "+inf", start=0, num=limit)]


def due_count() -> int:
    return int(rdb.zcount(REVIEW_QUEUE, "-inf", _ts_now()))


def queue_size() -> int:
    return int(rdb.zcard(REVIEW_QUEUE))


def stage_of(question_id: int) -> int:
    return int(rdb.hget(REVIEW_STAGE, str(question_id)) or 0)
