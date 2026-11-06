"""题库服务：岗位→类别权重映射、抽题策略、Redis 抽题池缓存。"""

import random
import re

from sqlalchemy.orm import Session as DBSession

from .models import InterviewAnswer, Question
from .redis_client import rdb

CATEGORIES = [
    "MYSQL", "REDIS", "JAVA", "JVM", "CONCURRENT", "SPRING", "NETWORK", "SCENARIO",
    "AI_APP", "AGENT", "FULLSTACK",
    "OS", "DISTRIBUTED", "ALGO", "PYTHON",
]

CATEGORY_NAMES = {
    "MYSQL": "MySQL",
    "REDIS": "Redis",
    "JAVA": "Java 基础",
    "JVM": "JVM",
    "CONCURRENT": "并发编程",
    "SPRING": "Spring",
    "NETWORK": "计算机网络",
    "SCENARIO": "场景设计",
    "AI_APP": "AI 应用开发",
    "AGENT": "Agent 开发",
    "FULLSTACK": "全栈开发",
    "OS": "操作系统",
    "DISTRIBUTED": "分布式",
    "ALGO": "算法",
    "PYTHON": "Python",
}

# 各岗位画像：类别 -> 出题权重
PROFILES = {
    "java": {"MYSQL": 3, "REDIS": 3, "JAVA": 2, "CONCURRENT": 2, "JVM": 1, "SPRING": 2, "NETWORK": 1, "SCENARIO": 1, "OS": 2, "DISTRIBUTED": 1, "ALGO": 1},
    "backend": {"MYSQL": 4, "REDIS": 4, "JAVA": 1, "NETWORK": 1, "SCENARIO": 2, "OS": 1, "DISTRIBUTED": 2, "ALGO": 1},
    "golang": {"MYSQL": 3, "REDIS": 3, "NETWORK": 2, "SCENARIO": 2, "OS": 1, "DISTRIBUTED": 1, "ALGO": 1},
    "python": {"MYSQL": 3, "REDIS": 3, "NETWORK": 1, "SCENARIO": 2, "ALGO": 1, "PYTHON": 3},
    "cpp": {"MYSQL": 3, "REDIS": 3, "NETWORK": 2, "SCENARIO": 2, "OS": 2, "ALGO": 1},
    "dba": {"MYSQL": 5, "REDIS": 4, "NETWORK": 1, "SCENARIO": 1},
    "test": {"MYSQL": 2, "REDIS": 2, "NETWORK": 1, "SCENARIO": 2},
    "frontend": {"NETWORK": 2, "SCENARIO": 2, "MYSQL": 1},
    "os_specialist": {"OS": 4, "MYSQL": 2, "REDIS": 1, "NETWORK": 2, "DISTRIBUTED": 1},
    "ai_app": {"AI_APP": 5, "AGENT": 2, "MYSQL": 2, "REDIS": 2, "SCENARIO": 2, "NETWORK": 1, "ALGO": 1, "PYTHON": 1},
    "agent": {"AGENT": 5, "AI_APP": 3, "MYSQL": 1, "REDIS": 1, "SCENARIO": 2, "ALGO": 1},
    "fullstack": {"FULLSTACK": 5, "MYSQL": 2, "REDIS": 2, "NETWORK": 2, "SCENARIO": 1, "ALGO": 1, "OS": 1},
    "default": {"MYSQL": 3, "REDIS": 3, "NETWORK": 1, "SCENARIO": 1},
}


def match_profile(position: str) -> tuple[str, dict]:
    """岗位文本 -> (画像名, 类别权重)。
    注意匹配顺序：javascript/fullstack 先于 java；agent/ai 先于含"开发"的兜底分支。
    """
    p = position.lower()
    if "前端" in p or "frontend" in p or "javascript" in p or "vue" in p or "react" in p:
        return "frontend", PROFILES["frontend"]
    if "全栈" in p or "fullstack" in p or "full stack" in p or "full-stack" in p:
        return "fullstack", PROFILES["fullstack"]
    if "agent" in p or "智能体" in p:
        return "agent", PROFILES["agent"]
    if (
        re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", p)  # \b 对中文失效，改用 ASCII 字符边界
        or "大模型" in p or "llm" in p or "aigc" in p or "nlp" in p
        or "机器学习" in p or "深度学习" in p or "人工智能" in p
    ):
        return "ai_app", PROFILES["ai_app"]
    if "java" in p or "spring" in p or "j2ee" in p:
        return "java", PROFILES["java"]
    if "golang" in p or "go语言" in p or " go " in p:
        return "golang", PROFILES["golang"]
    if "python" in p:
        return "python", PROFILES["python"]
    if "c++" in p or "cpp" in p:
        return "cpp", PROFILES["cpp"]
    if "dba" in p or "数据库" in p or "运维" in p or "sre" in p or "操作系统" in p or "linux" in p:
        if "操作系统" in p or "linux" in p:
            return "os_specialist", PROFILES["os_specialist"]
        return "dba", PROFILES["dba"]
    if "测试" in p or "qa" in p or "test" in p:
        return "test", PROFILES["test"]
    if "后端" in p or "backend" in p or "服务端" in p or "开发" in p:
        return "backend", PROFILES["backend"]
    return "default", PROFILES["default"]


def allocate(weights: dict[str, int], total: int) -> dict[str, int]:
    """按权重把 total 道题分配到各类别（最大余数法）"""
    wsum = sum(weights.values())
    raw = {c: total * w / wsum for c, w in weights.items()}
    base = {c: int(v) for c, v in raw.items()}
    rest = total - sum(base.values())
    if rest > 0:
        order = sorted(raw, key=lambda c: raw[c] - base[c], reverse=True)
        for c in order[:rest]:
            base[c] += 1
    return {c: n for c, n in base.items() if n > 0}


def invalidate_category_cache(category: str) -> None:
    rdb.delete(f"cache:bank:{category}")


def _category_pool(db: DBSession, category: str) -> list[Question]:
    """类别题目池：Redis LIST 缓存 10 分钟（cache-aside）"""
    key = f"cache:bank:{category}"
    if rdb.exists(key):
        ids = [int(x) for x in rdb.lrange(key, 0, -1)]
        if ids:
            return db.query(Question).filter(Question.id.in_(ids)).all()
        return []
    qs = db.query(Question).filter(Question.category == category).all()
    if qs:
        pipe = rdb.pipeline()
        pipe.delete(key)
        pipe.rpush(key, *[q.id for q in qs])
        pipe.expire(key, 600)
        pipe.execute()
    return qs


def pick_questions(db: DBSession, weights: dict[str, int], count: int) -> list[Question]:
    """按类别权重抽题：答错过的题优先重现，其次含薄弱知识点的未做题，最后随机旧题"""
    import json as _json

    from .redis_client import rdb as _rdb

    alloc = allocate(weights, count)

    # 历史答题情况
    wrong_ids: set[int] = set()
    seen_ids: set[int] = set()
    for qid, score in db.query(InterviewAnswer.question_id, InterviewAnswer.score).all():
        seen_ids.add(qid)
        if score is not None and score < 60:
            wrong_ids.add(qid)

    # 薄弱知识点集合（tag 级，驱动"换汤不换药"迁移：弱 tag 的题即使没直接答错也优先）
    weak_tags: set[str] = set()
    cached = _rdb.get("weakness:cache")
    if cached:
        try:
            data = _json.loads(cached)
            weak_tags = {n["tag"] for n in data.get("weak_points", [])}
        except ValueError:
            pass

    def weak_score(q: Question) -> int:
        """题目命中的薄弱知识点数（排序权重）"""
        return sum(1 for t in q.tags or [] if t in weak_tags)

    picked: list[Question] = []
    for cat, n in alloc.items():
        pool = _category_pool(db, cat)
        if not pool:
            continue
        wrong = [q for q in pool if q.id in wrong_ids]
        # 错题按"错得最频繁"排序（Redis ZSET 高频错题榜）
        wrong.sort(key=lambda q: -(rdb.zscore("question:hot", str(q.id)) or 0))
        unseen = [q for q in pool if q.id not in seen_ids]
        # 弱点迁移：含弱 tag 的未做题置顶（按命中弱 tag 数降序）
        unseen.sort(key=weak_score, reverse=True)
        seen = [q for q in pool if q.id in seen_ids and q.id not in wrong_ids]
        random.shuffle(seen)
        picked.extend((wrong + unseen + seen)[:n])
    return picked
