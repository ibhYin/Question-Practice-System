from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Question(Base):
    """题库：内置题 / 手动录入的真题 / AI 生成的题"""

    __tablename__ = "question"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    # MYSQL / REDIS / JAVA / JVM / CONCURRENT / SPRING / NETWORK / SCENARIO
    category: Mapped[str] = mapped_column(String(32))
    difficulty: Mapped[int] = mapped_column(Integer, default=2)  # 1易 2中 3难
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 知识点标签
    position_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 适用岗位
    # MANUAL 手动录入 / BUILTIN 内置 / AI 生成
    source: Mapped[str] = mapped_column(String(16), default="MANUAL")
    model_answer: Mapped[str] = mapped_column(Text, default="")  # 满分答案
    related_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 知识关联题 id（知识地图边）
    card_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 关联八股卡 id（答题时给出知识点）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        Index("ix_question_cat_diff", "category", "difficulty"),
        Index("ix_question_source", "source"),
    )


class InterviewSession(Base):
    """一场模拟面试"""

    __tablename__ = "interview_session"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    position: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(16), default="STANDARD")  # STANDARD/REVIEW
    question_count: Mapped[int] = mapped_column(Integer)
    question_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 出题顺序，持久化兜底
    # in_progress / finished / abandoned
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 总评
    weak_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 薄弱类别
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    answers: Mapped[list["InterviewAnswer"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class InterviewAnswer(Base):
    """一题的作答记录：你的回答 + 满分答案 + 评分点评"""

    __tablename__ = "interview_answer"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_session.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 第几题（1 起）
    user_answer: Mapped[str] = mapped_column(Text, default="")
    model_answer: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100，无 LLM 时为空
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    session: Mapped["InterviewSession"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship()


class StudyDoc(Base):
    """八股文库：体系长文档（陈述式知识，沉浸阅读，与面试题库完全分离）"""

    __tablename__ = "study_doc"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)  # Markdown 长文
    source: Mapped[str] = mapped_column(String(16), default="BUILTIN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StudyCard(Base):
    """八股文库：背诵卡片（Anki 式陈述知识点 + 关键点，带背诵进度）"""

    __tablename__ = "study_card"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))  # 知识点名（陈述式，非问句）
    content: Mapped[str] = mapped_column(Text)  # 陈述式正文
    points: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 关键点速记
    # new 未学 / learning 待巩固 / mastered 已背熟
    status: Mapped[str] = mapped_column(String(16), default="new")
    source: Mapped[str] = mapped_column(String(16), default="BUILTIN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KnowledgePack(Base):
    """知识点知识包：LLM 按需生成的系统级知识文档（完整原理/边界/变体问法/识别信号）。

    每个知识点一份、懒生成、永久复用——八股卡是速记锚点，知识包才是全面的知识来源。
    """

    __tablename__ = "knowledge_pack"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 知识点名
    category: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)  # Markdown 系统知识长文
    related_card_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 推荐速记卡
    related_question_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 典型考题
    source: Mapped[str] = mapped_column(String(16), default="AI")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
