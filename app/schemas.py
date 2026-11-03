from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ---------- 题库 ----------


class QuestionBase(BaseModel):
    title: str = Field(min_length=1)
    category: str
    difficulty: int = Field(default=2, ge=1, le=3)
    tags: list[str] = []
    position_tags: list[str] = []
    model_answer: str = ""


class QuestionCreate(QuestionBase):
    pass


class QuestionUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=3)
    tags: Optional[list[str]] = None
    position_tags: Optional[list[str]] = None
    model_answer: Optional[str] = None


class QuestionOut(QuestionBase):
    id: int
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- 面试 ----------


class SessionCreate(BaseModel):
    position: str = Field(min_length=1, max_length=64)
    count: int = Field(default=10, ge=1, le=30)
    categories: Optional[list[str]] = None  # 不传则按岗位智能映射


class QuestionBrief(BaseModel):
    """面试中的题目，不暴露满分答案"""

    id: int
    seq: int
    title: str
    category: str
    difficulty: int
    tags: list[str] = []

    model_config = {"from_attributes": True}


class InterviewStartOut(BaseModel):
    session_id: int
    position: str
    total: int
    question: QuestionBrief
    used_llm: bool  # 本场是否有 AI 生成的题


class AnswerSubmit(BaseModel):
    question_id: int
    user_answer: str = ""


class AnswerResult(BaseModel):
    question_id: int
    seq: int
    score: Optional[int] = None
    ai_comment: Optional[str] = None
    user_answer: str
    model_answer: str
    next_question: Optional[QuestionBrief] = None
    finished: bool


class SessionBrief(BaseModel):
    id: int
    position: str
    question_count: int
    status: str
    total_score: Optional[float]
    started_at: datetime
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AnswerDetail(BaseModel):
    seq: int
    question_id: int
    question_title: str
    category: str
    difficulty: int
    answered: bool
    user_answer: str = ""
    model_answer: str = ""
    score: Optional[int] = None
    ai_comment: Optional[str] = None


class SessionDetail(BaseModel):
    id: int
    position: str
    status: str
    question_count: int
    total_score: Optional[float]
    summary: Optional[str]
    weak_categories: Optional[list]
    started_at: datetime
    finished_at: Optional[datetime]
    answers: list[AnswerDetail]


# ---------- 错题复习 ----------


class ReviewAnswerIn(BaseModel):
    correct: bool
    user_answer: str = ""


# ---------- 设置 ----------


class LLMSettings(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class LLMSettingsOut(BaseModel):
    enabled: bool
    base_url: str
    model: str
    api_key_masked: str


class TestResult(BaseModel):
    ok: bool
    message: str
