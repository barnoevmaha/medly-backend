"""Importing this package registers every table with SQLModel's metadata."""
from app.models.analysis import AnalysisJob
from app.models.assistant import AssistantMessage
from app.models.audit import AuditEvent
from app.models.badge import UserBadge
from app.models.casebook import CaseImage, CaseReference, CaseView
from app.models.challenge import (
    Challenge,
    ChallengeAnswer,
    ChallengeChoice,
    ChallengeParticipant,
    ChallengeQuestion,
)
from app.models.community import Community, CommunityMember, CommunityMessage
from app.models.course import Course, Enrollment, Lesson, LessonProgress
from app.models.enums import (
    AnalysisStatus,
    EventType,
    LessonKind,
    Modality,
    PatientState,
    ProgressStatus,
    RiskLevel,
    Role,
    SessionStatus,
)
from app.models.quiz import Choice, Question, Quiz, QuizAttempt
from app.models.social import (
    Article,
    ArticleComment,
    ArticleLike,
    Resource,
    SavedItem,
)
from app.models.user import User
from app.models.virtual_patient import (
    VirtualPatientCase,
    VirtualPatientDecision,
    VirtualPatientOption,
    VirtualPatientSession,
    VirtualPatientStage,
)

__all__ = [
    "AnalysisJob",
    "AnalysisStatus",
    "Article",
    "ArticleComment",
    "ArticleLike",
    "AssistantMessage",
    "AuditEvent",
    "CaseImage",
    "CaseReference",
    "CaseView",
    "Challenge",
    "ChallengeAnswer",
    "ChallengeChoice",
    "ChallengeParticipant",
    "ChallengeQuestion",
    "Choice",
    "Community",
    "CommunityMember",
    "CommunityMessage",
    "Course",
    "Enrollment",
    "EventType",
    "Lesson",
    "LessonKind",
    "LessonProgress",
    "Modality",
    "PatientState",
    "ProgressStatus",
    "Question",
    "Quiz",
    "QuizAttempt",
    "Resource",
    "RiskLevel",
    "Role",
    "SavedItem",
    "SessionStatus",
    "User",
    "UserBadge",
    "VirtualPatientCase",
    "VirtualPatientDecision",
    "VirtualPatientOption",
    "VirtualPatientSession",
    "VirtualPatientStage",
]
