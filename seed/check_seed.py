"""题库自检脚本：跨文件重复标题 / 答案字数 / 难度范围 / 类别合法。

用法：.venv/bin/python -m seed.check_seed
新增题目后先跑本脚本再导入，确保零脏数据入库。
"""

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.question_bank import CATEGORY_NAMES  # noqa: E402

MIN_ANSWER_LEN = 120


def main() -> int:
    seen: dict[tuple[str, str], str] = {}
    problems: list[str] = []
    total = 0
    per_cat: dict[str, int] = {}

    for f in sorted(Path(__file__).parent.glob("*.yaml")):
        if f.name.startswith("study_"):
            continue  # 八股文库走 seed/check_study.py（顶层结构不同：doc+cards）
        items = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        for item in items:
            cat = item.get("category") or f.stem.upper()
            title = str(item.get("title", "")).strip()
            ans = str(item.get("answer", "")).strip()
            diff = int(item.get("difficulty", 2))

            if cat not in CATEGORY_NAMES:
                problems.append(f"{f.name}: 未知类别 {cat} - {title[:25]}")
                continue
            if not title:
                problems.append(f"{f.name}: 空标题")
                continue
            if len(ans) < MIN_ANSWER_LEN:
                problems.append(f"{f.name}: 答案过短({len(ans)}字 < {MIN_ANSWER_LEN}) - {title[:25]}")
            if not 1 <= diff <= 3:
                problems.append(f"{f.name}: 难度非法 {diff} - {title[:25]}")
            key = (re.sub(r"\s+", "", title), cat)
            if key in seen:
                problems.append(f"{f.name}: 标题重复(与 {seen[key]}) - {title[:25]}")
            seen[key] = f.name
            per_cat[cat] = per_cat.get(cat, 0) + 1
            total += 1

    print(f"合计 {total} 题，问题 {len(problems)} 个")
    for p in problems:
        print("  ✗", p)
    print("分类分布:", dict(sorted(per_cat.items())))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
