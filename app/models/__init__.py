"""Importing this package registers every table with SQLModel's metadata."""
from app.models.analysis import AnalysisJob
from app.models.assistant import AssistantMessage
from app.models.audit import AuditEvent
from app.models.course import Course, Enrollment, Lesson, LessonProgress
from app.models.enums import (
    AnalysisStatus,
    EventType,
    LessonKind,
    Modality,
    ProgressStatus,
    RiskLevel,
    Role,
)
from app.models.quiz import Choice, Question, Quiz, QuizAttempt
from app.models.user import User

__all__ = [
    "AnalysisJob",
    "AnalysisStatus",
    "AssistantMessage",
    "AuditEvent",
    "Choice",
    "Course",
    "Enrollment",
    "EventType",
    "Lesson",
    "LessonKind",
    "LessonProgress",
    "Modality",
    "ProgressStatus",
    "Question",
    "Quiz",
    "QuizAttempt",
    "RiskLevel",
    "Role",
    "User",
]
