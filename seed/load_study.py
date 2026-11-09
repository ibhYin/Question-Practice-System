"""导入八股文库内容（seed/study_*.yaml → study_doc / study_card，幂等）。

文件结构：
    category: MYSQL        # 顶部显式类别
    doc: { title, content }
    cards: [ { title, content, points } ]

用法：.venv/bin/python -m seed.load_study
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import StudyCard, StudyDoc  # noqa: E402
from app.question_bank import CATEGORY_NAMES  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    docs_added, cards_added, skipped = 0, 0, 0
    try:
        for f in sorted(Path(__file__).parent.glob("study_*.yaml")):
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            category = data.get("category", "")
            if category not in CATEGORY_NAMES:
                print(f"[跳过] {f.name}：未知类别 {category}")
                continue

            doc = data.get("doc")
            if doc and doc.get("title"):
                exists = (
                    db.query(StudyDoc)
                    .filter(StudyDoc.title == doc["title"], StudyDoc.source == "BUILTIN")
                    .first()
                )
                if not exists:
                    db.add(
                        StudyDoc(
                            category=category,
                            title=str(doc["title"]).strip(),
                            content=str(doc.get("content", "")).strip(),
                            source="BUILTIN",
                        )
                    )
                    docs_added += 1
                else:
                    # 文档按 title 覆盖更新（图表/内容迭代后重跑导入即可刷新）
                    exists.content = str(doc.get("content", "")).strip()

            for card in data.get("cards") or []:
                title = str(card.get("title", "")).strip()
                if not title:
                    continue
                exists = (
                    db.query(StudyCard)
                    .filter(StudyCard.title == title, StudyCard.source == "BUILTIN")
                    .first()
                )
                if exists:
                    skipped += 1
                    continue
                db.add(
                    StudyCard(
                        category=category,
                        title=title,
                        content=str(card.get("content", "")).strip(),
                        points=card.get("points") or [],
                        status="new",
                        source="BUILTIN",
                    )
                )
                cards_added += 1
            print(f"[文件] {f.name}（{category}）")
        db.commit()
        print(f"\n导入完成：新增文档 {docs_added} 篇、卡片 {cards_added} 张，跳过重复 {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
