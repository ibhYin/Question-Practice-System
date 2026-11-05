"""八股文库自检：类别合法 / 字段完整 / 正文长度 / 跨文件重复标题 / 卡片非问句。

用法：.venv/bin/python -m seed.check_study
"""

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.question_bank import CATEGORY_NAMES  # noqa: E402

MIN_CONTENT_LEN = 80


def looks_like_question(title: str) -> bool:
    """八股卡片标题应是陈述式知识点，不应是问句"""
    return title.strip().endswith(("？", "?"))


def main() -> int:
    seen: dict[str, str] = {}
    problems: list[str] = []
    total_docs, total_cards = 0, 0

    for f in sorted(Path(__file__).parent.glob("study_*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        category = data.get("category", "")
        if category not in CATEGORY_NAMES:
            problems.append(f"{f.name}: 未知类别 {category}")
            continue

        doc = data.get("doc") or {}
        if not doc.get("title") or len(str(doc.get("content", ""))) < 300:
            problems.append(f"{f.name}: doc 缺失或正文过短（{category}）")
        else:
            total_docs += 1

        cards = data.get("cards") or []
        if len(cards) < 8:
            problems.append(f"{f.name}: {category} 卡片过少（{len(cards)} < 8）")
        for card in cards:
            title = str(card.get("title", "")).strip()
            content = str(card.get("content", "")).strip()
            if not title:
                problems.append(f"{f.name}: {category} 空卡片标题")
                continue
            if looks_like_question(title):
                problems.append(f"{f.name}: {category} 卡片标题是问句（应陈述式）- {title[:25]}")
            if len(content) < MIN_CONTENT_LEN:
                problems.append(f"{f.name}: {category} 卡片正文过短 - {title[:25]}")
            if not card.get("points"):
                problems.append(f"{f.name}: {category} 卡片缺关键点 - {title[:25]}")
            key = re.sub(r"\s+", "", title)
            if key in seen:
                problems.append(f"{f.name}: {category} 标题重复(与 {seen[key]}) - {title[:25]}")
            seen[key] = f"{category}"
            total_cards += 1

    print(f"文档 {total_docs} 篇，卡片 {total_cards} 张，问题 {len(problems)} 个")
    for p in problems:
        print("  ✗", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
