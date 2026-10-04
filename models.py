from pydantic import BaseModel


class Plan(BaseModel):
    clear: bool
    topic: str
    key_points: list[str]
    question_for_student: str


class Question(BaseModel):
    question: str
    ideal_answer: str


class Quiz(BaseModel):
    topic: str
    questions: list[Question]


class QuestionFeedback(BaseModel):
    correct: bool
    comment: str


class Evaluation(BaseModel):
    feedback: list[QuestionFeedback]
    weak_points: list[str]
    summary: str
