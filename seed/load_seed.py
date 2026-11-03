"""导入内置题库到 MySQL（幂等：按 title + source=BUILTIN 去重，可重复执行）。

用法：.venv/bin/python -m seed.load_seed
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Question  # noqa: E402
from app.question_bank import CATEGORY_NAMES, invalidate_category_cache  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    added, skipped = 0, 0
    try:
        for f in sorted(Path(__file__).parent.glob("*.yaml")):
            default_cat = f.stem.upper()  # mysql.yaml -> MYSQL
            items = yaml.safe_load(f.read_text(encoding="utf-8")) or []
            file_added = 0
            for item in items:
                # 文件名不是合法类别时（如 extras 批次文件），回退到每题的显式 category 字段
                category = item.get("category") or default_cat
                if category not in CATEGORY_NAMES:
                    print(f"[跳过] {f.name} 中未知类别：{category} - {str(item.get('title'))[:30]}")
                    continue
                title = str(item["title"]).strip()
                exists = (
                    db.query(Question)
                    .filter(Question.title == title, Question.source == "BUILTIN")
                    .first()
                )
                if exists:
                    skipped += 1
                    continue
                db.add(
                    Question(
                        title=title,
                        category=category,
                        difficulty=int(item.get("difficulty", 2)),
                        tags=item.get("tags") or [],
                        position_tags=item.get("position_tags") or [],
                        source="BUILTIN",
                        model_answer=str(item.get("answer", "")).strip(),
                    )
                )
                added += 1
                file_added += 1
            print(f"[文件] {f.name}：{len(items)} 题（新增 {file_added}）")
        db.commit()
        # 清空全部抽题池缓存，让新题立即可见
        for cat in CATEGORY_NAMES:
            invalidate_category_cache(cat)
        print(f"\n导入完成：新增 {added} 题，跳过重复 {skipped} 题")
    finally:
        db.close()


if __name__ == "__main__":
    main()
