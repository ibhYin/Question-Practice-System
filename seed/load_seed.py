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
            category = f.stem.upper()  # mysql.yaml -> MYSQL
            if category not in CATEGORY_NAMES:
                print(f"[跳过] 未知类别文件：{f.name}")
                continue
            items = yaml.safe_load(f.read_text(encoding="utf-8")) or []
            for item in items:
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
                        category=item.get("category") or category,
                        difficulty=int(item.get("difficulty", 2)),
                        tags=item.get("tags") or [],
                        position_tags=item.get("position_tags") or [],
                        source="BUILTIN",
                        model_answer=str(item.get("answer", "")).strip(),
                    )
                )
                added += 1
            print(f"[文件] {f.name}：{len(items)} 题")
        db.commit()
        # 清空全部抽题池缓存，让新题立即可见
        for cat in CATEGORY_NAMES:
            invalidate_category_cache(cat)
        print(f"\n导入完成：新增 {added} 题，跳过重复 {skipped} 题")
    finally:
        db.close()


if __name__ == "__main__":
    main()
