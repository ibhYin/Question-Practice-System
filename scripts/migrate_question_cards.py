"""轻量迁移：为已存在的 question 表补 card_ids 列（幂等）。

用法：.venv/bin/python -m scripts.migrate_question_cards
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app.database import engine  # noqa: E402


def main() -> None:
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("question")]
    if "card_ids" in cols:
        print("card_ids 列已存在，无需迁移")
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE question ADD COLUMN card_ids JSON NULL"))
    print("✅ 已为 question 表添加 card_ids 列")


if __name__ == "__main__":
    main()
