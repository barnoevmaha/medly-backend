"""Shared enumerations."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    STUDENT = "student"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class RiskLevel(str, Enum):
    """How much harm a given AI interaction could cause if it were wrong."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PatientState(str, Enum):
    """How the virtual patient is doing. Only the game engine sets this."""

    STABLE = "stable"
    IMPROVING = "improving"
    DETERIORATING = "deteriorating"
    CRITICAL = "critical"
    RECOVERED = "recovered"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (PatientState.RECOVERED, PatientState.FAILED)


class SessionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class EventType(str, Enum):
    ASSISTANT_QUERY = "assistant_query"
    ASSISTANT_BLOCKED = "assistant_blocked"
    ANALYSIS_REQUESTED = "analysis_requested"
    ANALYSIS_RETURNED = "analysis_returned"
    ANALYSIS_ACCEPTED = "analysis_accepted"
    ANALYSIS_OVERRIDDEN = "analysis_overridden"
    QUIZ_SUBMITTED = "quiz_submitted"
    CERTIFICATION_EARNED = "certification_earned"
    LESSON_COMPLETED = "lesson_completed"
    VP_SESSION_STARTED = "vp_session_started"
    VP_DECISION_MADE = "vp_decision_made"
    VP_SESSION_COMPLETED = "vp_session_completed"


class LessonKind(str, Enum):
    READING = "reading"
    VIDEO = "video"
    INTERACTIVE = "interactive"
    CASE = "case"


class ProgressStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Modality(str, Enum):
    XRAY = "xray"
    CT = "ct"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
