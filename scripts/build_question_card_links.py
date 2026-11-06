"""题↔八股卡建链：为每道面试题挂上"能回答它的知识点卡"（question.card_ids）。

规则（确定性）：同类别下，question.tags 在 card.title + points 中的命中数为主分，
card.title 关键词出现在 question.title 中为加分；score ≥1 取 top5。

用法：
  .venv/bin/python -m scripts.build_question_card_links           # 规则建链（覆盖）
  .venv/bin/python -m scripts.build_question_card_links --llm     # 规则 + LLM 补链（无规则题批量判选）
  .venv/bin/python -m scripts.build_question_card_links --dry-run # 只看统计
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Question, StudyCard  # noqa: E402
from app.question_bank import invalidate_category_cache  # noqa: E402

MAX_CARDS = 5


def card_text(card: StudyCard) -> str:
    return card.title + " " + " ".join(card.points or [])


def card_score(q: Question, card: StudyCard) -> int:
    """question.tags 在卡 title+points 中的命中数 + 标题关键词互现加分"""
    text = card_text(card)
    score = sum(1 for t in q.tags or [] if t and t in text)
    # 卡标题的关键词（≥2 字）出现在题目里也算关联信号
    if any(kw in q.title for kw in [card.title] if len(card.title) >= 4):
        score += 1
    return score


def main(dry_run: bool = False, use_llm: bool = False) -> None:
    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        cards = db.query(StudyCard).all()
        cards_by_cat: dict[str, list[StudyCard]] = {}
        for c in cards:
            cards_by_cat.setdefault(c.category, []).append(c)

        mapping: dict[int, list[int]] = {}
        for q in questions:
            cands = []
            for card in cards_by_cat.get(q.category, []):
                s = card_score(q, card)
                if s >= 1:
                    cands.append((s, card.id))
            cands.sort(reverse=True)
            ids = [cid for _, cid in cands[:MAX_CARDS]]
            if ids:
                mapping[q.id] = ids

        linked = len(mapping)
        print(f"规则建链：{linked}/{len(questions)} 题挂上八股卡")

        if use_llm:
            from app.llm import is_enabled, pick_cards_for_question

            if not is_enabled():
                print("LLM 未配置，跳过补链")
            else:
                uncovered = [q for q in questions if q.id not in mapping]
                print(f"LLM 补链：{len(uncovered)} 题无规则边，批量判选…")
                added = 0
                cards_by_cat_all = cards_by_cat
                for i in range(0, len(uncovered), 15):
                    batch = uncovered[i : i + 15]
                    try:
                        results = pick_cards_for_question(batch, cards_by_cat_all)
                    except Exception as e:
                        print(f"  批次 {i // 15 + 1} 失败（{type(e).__name__}），跳过")
                        continue
                    idmap = {c.id: c for c in cards}
                    for qid, card_ids in results:
                        valid = [cid for cid in card_ids if cid in idmap]
                        if valid:
                            mapping[qid] = valid[:MAX_CARDS]
                            added += 1
                    print(f"  批次 {i // 15 + 1}/{(len(uncovered) + 14) // 15} 完成")
                print(f"LLM 补链：新增 {added} 题，合计 {len(mapping)}/{len(questions)} 题")

        if dry_run:
            qmap = {q.id: q for q in questions}
            cmap = {c.id: c for c in cards}
            for qid, cids in list(mapping.items())[:3]:
                q = qmap[qid]
                names = [cmap[cid].title for cid in cids]
                print(f"  示例 [{q.category}] {q.title[:26]} → {names}")
            return

        for q in questions:
            q.card_ids = mapping.get(q.id) or None
        db.commit()
        cats = {q.category for q in questions}
        for cat in cats:
            invalidate_category_cache(cat)
        print("✅ 题卡映射已写库")
    finally:
        db.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv, use_llm="--llm" in sys.argv)
