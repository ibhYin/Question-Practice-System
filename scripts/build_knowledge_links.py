"""知识关联构建：为题目建立 related_ids 关系网（知识地图的边）。

两级构建：
1. 规则边（确定性，默认执行）：同类别且 tags 有交集互相关联——每题最多 6 条，
   优先 tag 交集多、难度接近的题。
2. LLM 边（--llm，需配置 key）：对无规则边的题目做跨类别配对判定
   （Redis fork→OS 写时复制 这类规则覆盖不到的联系），每次批 20 对、从严格控制。

用法：
  .venv/bin/python -m scripts.build_knowledge_links            # 规则边（覆盖重建）
  .venv/bin/python -m scripts.build_knowledge_links --llm      # 规则边 + LLM 跨类别补边
  .venv/bin/python -m scripts.build_knowledge_links --dry-run  # 只看统计
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Question  # noqa: E402
from app.question_bank import invalidate_category_cache  # noqa: E402

MAX_LINKS = 6  # 每题最多关联数（防止图谱过密失去导航价值）


def similarity(a: Question, b: Question) -> tuple[int, int]:
    """(tag 交集数, 难度差) —— 交集越大越相关，难度差作为次级排序"""
    ta, tb = set(a.tags or []), set(b.tags or [])
    return len(ta & tb), abs((a.difficulty or 2) - (b.difficulty or 2))


def build_rule_links(db, questions) -> dict[int, set[int]]:
    related: dict[int, set[int]] = {}
    by_cat: dict[str, list[Question]] = {}
    for q in questions:
        by_cat.setdefault(q.category, []).append(q)
    for cat, qs in by_cat.items():
        for i, a in enumerate(qs):
            candidates = []
            for j, b in enumerate(qs):
                if i == j:
                    continue
                inter, diff_gap = similarity(a, b)
                if inter >= 1:
                    candidates.append((inter, -diff_gap, b.id))
            candidates.sort(reverse=True)
            for _, _, bid in candidates[:MAX_LINKS]:
                related.setdefault(a.id, set()).add(bid)
                related.setdefault(bid, set()).add(a.id)
    return related


def build_llm_links(db, questions, related) -> int:
    """对没有任何关联的题，用 LLM 判定跨类别配对（每次批 20 对）。"""
    from app.llm import is_enabled, judge_question_pairs

    if not is_enabled():
        print("LLM 未配置，跳过跨类别补边")
        return 0
    orphan = [q for q in questions if not related.get(q.id)]
    if not orphan:
        print("无孤立题目，跳过 LLM 补边")
        return 0
    # 孤立题 × 高频方向代表题做配对（限制规模：每孤立题配 4 个跨类别候选）
    cats = ["MYSQL", "REDIS", "JVM", "OS", "NETWORK", "CONCURRENT", "PYTHON", "AI_APP"]
    anchors = [q for q in questions if q.category in cats and q.id in related][:40]
    pairs, seen = [], set()
    for o in orphan:
        for anchor in anchors:
            if anchor.category == o.category:
                continue
            key = (o.id, anchor.id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"a_id": o.id, "a_title": o.title, "b_id": anchor.id, "b_title": anchor.title})
            if len(pairs) >= 200:  # 成本上限：200 对 = 10 次调用
                break
        if len(pairs) >= 200:
            break
    added = 0
    for i in range(0, len(pairs), 20):
        batch = pairs[i : i + 20]
        try:
            results = judge_question_pairs(batch)
        except Exception as e:
            print(f"  LLM 批次 {i // 20 + 1} 失败（{type(e).__name__}），跳过")
            continue
        idmap = {q.id: q for q in questions}
        for r in results:
            if not r["linked"]:
                continue
            a, b = idmap.get(r["a_id"]), idmap.get(r["b_id"])
            if a and b:
                related.setdefault(a.id, set()).add(b.id)
                related.setdefault(b.id, set()).add(a.id)
                added += 1
        print(f"  LLM 批次 {i // 20 + 1}/{(len(pairs) + 19) // 20} 完成")
    return added


def main(dry_run: bool = False, use_llm: bool = False) -> None:
    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        related = build_rule_links(db, questions)

        linked = sum(1 for q in questions if related.get(q.id))
        edges = sum(len(s) for s in related.values())
        print(f"规则边：{linked}/{len(questions)} 题有关联，边数（含双向）{edges}")

        if use_llm:
            added = build_llm_links(db, questions, related)
            print(f"LLM 补边：新增 {added} 条")
            linked = sum(1 for q in questions if related.get(q.id))
            print(f"合计：{linked}/{len(questions)} 题有关联")

        if dry_run:
            sample = [(q, related[q.id]) for q in questions if related.get(q.id)][:3]
            for q, rels in sample:
                print(f"  示例 [{q.category}] {q.title[:30]} → {len(rels)} 条关联")
            return

        for q in questions:
            q.related_ids = sorted(related.get(q.id, []))
        db.commit()
        cats = {q.category for q in questions}
        for cat in cats:
            invalidate_category_cache(cat)
        print("✅ 关联已写库")
    finally:
        db.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv, use_llm="--llm" in sys.argv)
