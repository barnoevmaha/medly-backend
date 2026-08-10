"""Seed the database with the curriculum and demo accounts.

    python -m app.seed
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from sqlmodel import Session, select

from app.db import engine, init_db
from app.models.audit import AuditEvent
from app.models.course import Course, Enrollment, Lesson, LessonProgress
from app.models.enums import EventType, LessonKind, ProgressStatus, RiskLevel, Role
from app.models.quiz import Choice, Question, Quiz
from app.models.user import User
from app.security import hash_password

DEMO_PASSWORD = "medly1234"


# --------------------------------------------------------------------------
# Curriculum
# --------------------------------------------------------------------------

COURSES = [
    {
        "slug": "ai-in-medicine-foundations",
        "title": "AI in Medicine: Foundations",
        "summary": "What these models actually do, in language that survives contact with a ward round.",
        "track": "ai-foundations",
        "level": "beginner",
        "emoji": "🧠",
        "duration_minutes": 75,
        "order": 1,
        "lessons": [
            {
                "title": "What a medical AI model is, and is not",
                "kind": LessonKind.READING,
                "duration_minutes": 12,
                "key_point": "A model outputs a probability, not a diagnosis. The gap between "
                             "those two things is where patients get hurt.",
                "body_md": (
                    "## Pattern matching, not reasoning\n\n"
                    "A convolutional network trained on chest radiographs learns statistical "
                    "regularities between pixel arrangements and labels. It has no concept of a "
                    "lung, no model of disease, and no awareness that a person is attached to "
                    "the image.\n\n"
                    "This matters because it predicts how these systems fail. They do not make "
                    "human mistakes. They fail on inputs that look unusual to them but ordinary "
                    "to you: a rotated film, an unfamiliar scanner, a body habitus "
                    "under-represented in training.\n\n"
                    "## Three questions worth asking of any model\n\n"
                    "1. What exactly was it trained to predict, and how was the label defined?\n"
                    "2. Which population and equipment produced the training data?\n"
                    "3. What does it do when the answer is none of the above?\n\n"
                    "Most deployed imaging models have no way to say *I have not seen anything "
                    "like this*. They return a confident answer regardless. That is a property "
                    "of the architecture, not a bug someone forgot to fix."
                ),
            },
            {
                "title": "Sensitivity, specificity, and the prevalence trap",
                "kind": LessonKind.READING,
                "duration_minutes": 15,
                "key_point": "A 95%/95% model in a 1-in-1000 population produces roughly "
                             "98 false alarms for every 2 true ones.",
                "body_md": (
                    "## The numbers vendors quote\n\n"
                    "**Sensitivity** — of the people who have it, what fraction does the test catch?\n"
                    "**Specificity** — of the people who do not, what fraction does it correctly clear?\n\n"
                    "Both are properties of the test. Neither answers the question you actually "
                    "have in front of a patient, which is: *this came back positive — what now?*\n\n"
                    "## Working it through\n\n"
                    "Model at 95% sensitivity and 95% specificity. Condition affects 1 in 1,000. "
                    "Screen 100,000 people:\n\n"
                    "- 100 have it. The model flags 95.\n"
                    "- 99,900 do not. The model wrongly flags 4,995.\n"
                    "- Total positives: 5,090. True ones: 95.\n\n"
                    "**Positive predictive value: 1.9%.** Ninety-eight of every hundred alarms "
                    "are false, from a model you would describe as 95% accurate.\n\n"
                    "Nothing about the model changed. Only the population did. This is why "
                    "'validated at 95% accuracy' is not an answer to 'should we deploy this here'."
                ),
            },
            {
                "title": "How imaging models fail in the wild",
                "kind": LessonKind.CASE,
                "duration_minutes": 14,
                "key_point": "Models learn whatever correlates with the label, including things "
                             "that have nothing to do with the disease.",
                "body_md": (
                    "## Shortcut learning\n\n"
                    "A widely cited finding: pneumonia classifiers that performed excellently "
                    "in-house degraded sharply at other hospitals. The models had partly learned "
                    "to recognise the *portable radiograph marker*. Sicker patients get portable "
                    "films, so the marker correlated with disease. The shortcut worked in "
                    "training and broke everywhere else.\n\n"
                    "Similar shortcuts have been documented for chest drains, laterality markers, "
                    "and text burned into the image.\n\n"
                    "## Dataset shift\n\n"
                    "Performance drops when deployment data differs from training data. Sources "
                    "include a scanner upgrade, a protocol change, a different patient mix, or "
                    "simply time passing.\n\n"
                    "The uncomfortable part: this degradation is silent. Nothing alerts. The "
                    "model keeps returning confident outputs while quietly getting worse, and "
                    "without prospective monitoring nobody finds out."
                ),
            },
            {
                "title": "Reading a saliency map honestly",
                "kind": LessonKind.INTERACTIVE,
                "duration_minutes": 12,
                "key_point": "A heatmap tells you which pixels mattered, not why. It is a "
                             "prompt to look again, never an explanation.",
                "body_md": (
                    "## What the colours mean\n\n"
                    "Grad-CAM and similar methods highlight regions whose perturbation changes "
                    "the output. That is a statement about the model's sensitivity to pixels, "
                    "not about anatomy or pathology.\n\n"
                    "## Why over-reading is easy\n\n"
                    "A warm patch over the right lower zone alongside a 'pneumonia' label reads "
                    "as *the model found consolidation there*. It does not mean that. Published "
                    "sanity checks have shown some saliency methods produce visually similar maps "
                    "even when model weights are randomised.\n\n"
                    "## How to use one well\n\n"
                    "Treat it as a pointer: *look here again*. If you look and see nothing, the "
                    "correct conclusion is that you see nothing — not that you must be missing "
                    "what the machine can see."
                ),
            },
        ],
    },
    {
        "slug": "ai-safety-and-ethics-certification",
        "title": "AI Safety & Ethics Certification",
        "summary": "The mandatory module. Pass this and AI-assisted analysis unlocks.",
        "track": "safety",
        "level": "core",
        "emoji": "🛡️",
        "duration_minutes": 60,
        "order": 2,
        "is_certification": True,
        "lessons": [
            {
                "title": "Automation bias, and the order you look in",
                "kind": LessonKind.READING,
                "duration_minutes": 14,
                "key_point": "Commit your own read before you see the model's. Order of "
                             "exposure changes what you conclude.",
                "body_md": (
                    "## Two failure modes\n\n"
                    "**Errors of commission** — you follow a wrong AI recommendation you would "
                    "have caught on your own.\n\n"
                    "**Errors of omission** — the AI flags nothing, so you stop searching, and "
                    "you miss what was there.\n\n"
                    "The second is harder to detect and probably more common. It leaves no trace: "
                    "there is no wrong recommendation to point at afterwards, only a finding "
                    "nobody looked for.\n\n"
                    "## Who is most affected\n\n"
                    "Counter-intuitively, less experienced readers are more susceptible — they "
                    "have less internal evidence to weigh the suggestion against. Which means "
                    "students, using these tools during training, are the group most at risk.\n\n"
                    "## The countermeasure\n\n"
                    "Sequencing. This platform makes you record your interpretation before the "
                    "model output is revealed, and the server refuses to run the model until you "
                    "have. Your read stays yours, and disagreement becomes visible instead of "
                    "silently resolved in the model's favour."
                ),
            },
            {
                "title": "Confidence, calibration, and knowing when to stop",
                "kind": LessonKind.READING,
                "duration_minutes": 12,
                "key_point": "Deep networks are systematically overconfident. A stated 0.94 "
                             "is not a 94% chance of being right.",
                "body_md": (
                    "## Calibration\n\n"
                    "A calibrated model is right about 80% of the time when it says 80%. Modern "
                    "deep networks are usually not calibrated out of the box, and skew "
                    "overconfident — partly a side effect of how they are trained.\n\n"
                    "## What this platform does\n\n"
                    "Anything below the configured threshold is flagged as uncertain and routed "
                    "to a human rather than displayed as a result. The threshold is visible in "
                    "the governance dashboard, not buried in a config file.\n\n"
                    "## What to ask\n\n"
                    "When a vendor shows you a confidence score: calibrated against what, "
                    "measured on which population, and how recently? An uncalibrated number tells "
                    "you about the model's enthusiasm, not about the patient."
                ),
            },
            {
                "title": "Ethics: consent, accountability, equity, transparency",
                "kind": LessonKind.READING,
                "duration_minutes": 16,
                "key_point": "When an AI-assisted decision harms someone, the clinician is "
                             "accountable. The model cannot be.",
                "body_md": (
                    "## Consent\n\n"
                    "Did the patients whose scans trained this model agree to that use? Broad "
                    "consent for research is not obviously consent for commercial model "
                    "development, and the distinction is still being argued in court.\n\n"
                    "## Accountability\n\n"
                    "Liability sits with the clinician who acted, and to varying degrees with the "
                    "institution that deployed the tool. 'The algorithm said so' has never been a "
                    "defence. If you cannot explain why you accepted a recommendation, you are "
                    "not in a position to accept it.\n\n"
                    "## Equity\n\n"
                    "Aggregate performance hides subgroup failure. A model can post excellent "
                    "overall numbers while performing materially worse for one group. If "
                    "performance was not reported separately across the groups it will be used "
                    "on, assume it was not measured.\n\n"
                    "## Transparency\n\n"
                    "Does the patient know an AI was involved? Emerging regulation increasingly "
                    "says they should. This platform's position is that disclosure is not "
                    "configurable — every AI output is labelled, always."
                ),
            },
            {
                "title": "Regulation: what clearance does and does not mean",
                "kind": LessonKind.READING,
                "duration_minutes": 10,
                "key_point": "Most radiology AI is cleared as equivalent to an existing device, "
                             "not proven to improve outcomes.",
                "body_md": (
                    "## The pathways\n\n"
                    "In the US, most imaging AI reaches market via **FDA 510(k)**: a claim of "
                    "substantial equivalence to a legally marketed predicate. In the EU, **CE "
                    "marking** under the MDR, with class depending on risk.\n\n"
                    "## What that establishes\n\n"
                    "That the device is comparable to something already sold. It does not "
                    "establish that patients treated with it do better — that would require "
                    "prospective clinical trials, which most of these tools do not have.\n\n"
                    "## Intended use is the boundary\n\n"
                    "Clearance covers a stated intended use: a modality, a population, a "
                    "question. Using the tool outside that scope puts you outside both the "
                    "evidence and the approval, and the liability lands on you."
                ),
            },
        ],
    },
    {
        "slug": "supervised-imaging-practice",
        "title": "Supervised Imaging Practice",
        "summary": "Work simulated X-ray and CT cases with the safety workflow enforced end to end.",
        "track": "practice",
        "level": "intermediate",
        "emoji": "🩻",
        "duration_minutes": 90,
        "order": 3,
        "lessons": [
            {
                "title": "The four-step workflow",
                "kind": LessonKind.INTERACTIVE,
                "duration_minutes": 10,
                "key_point": "Case, then your read, then the model, then your decision. "
                             "The server enforces the order.",
                "body_md": (
                    "## Why the order is fixed\n\n"
                    "1. **Open the case.** Modality and reference only.\n"
                    "2. **Record your reading.** Your interpretation, before any AI output. "
                    "The API returns 409 if you skip this.\n"
                    "3. **Run the model.** Findings, confidence per finding, and the model's "
                    "stated limitations.\n"
                    "4. **Decide.** Your final call, and whether you agreed with the model.\n\n"
                    "Step 4 produces the metric that matters: your override rate. A student who "
                    "never disagrees with the model is not reading the images, and the "
                    "governance dashboard makes that visible to instructors.\n\n"
                    "Roughly one case in four is deliberately low-confidence, so you meet the "
                    "uncertain path here rather than for the first time in a hospital."
                ),
            },
        ],
    },
]


CERT_QUESTIONS = [
    {
        "prompt": "A chest X-ray model reports 95% sensitivity and 95% specificity. It is used to "
                  "screen a population where the condition affects 1 in 1,000. Roughly what "
                  "proportion of its positive results will be true positives?",
        "kind": "single",
        "explanation": "Around 2%. With 100,000 screened: 95 true positives against 4,995 false "
                       "positives. Predictive value depends on prevalence, so a model's headline "
                       "accuracy tells you almost nothing without knowing the population.",
        "choices": [
            ("About 2%", True),
            ("About 50%", False),
            ("About 95%", False),
            ("About 80%", False),
        ],
    },
    {
        "prompt": "Which of the following are examples of automation bias? Select all that apply.",
        "kind": "multi",
        "explanation": "Both commission (following a wrong recommendation you would have caught) "
                       "and omission (stopping your own search because the AI flagged nothing) "
                       "are automation bias. Disagreeing after review and escalating uncertainty "
                       "are the behaviours we want.",
        "choices": [
            ("Accepting an AI finding you would otherwise have questioned", True),
            ("Stopping your own search because the AI reported nothing", True),
            ("Disagreeing with the AI after reviewing the image yourself", False),
            ("Escalating a low-confidence output to a senior clinician", False),
        ],
    },
    {
        "prompt": "A saliency heatmap highlights the right lower zone on a radiograph the model "
                  "labelled 'pneumonia'. What does that tell you?",
        "kind": "single",
        "explanation": "Only that those pixels influenced the output. Saliency methods do not "
                       "explain reasoning, and some produce similar maps even with randomised "
                       "weights. Treat it as a prompt to look again, not as evidence.",
        "choices": [
            ("That those pixels most influenced the model's output", True),
            ("That the model detected consolidation in that region", False),
            ("That the diagnosis is confirmed in that location", False),
            ("That the model reasoned about the anatomy there", False),
        ],
    },
    {
        "prompt": "You are about to ask an AI assistant about a case. Which details must never "
                  "be included? Select all that apply.",
        "kind": "multi",
        "explanation": "Anything identifying. Medical record numbers, dates of birth and contact "
                       "details are all identifiers. Clinical abstractions such as age band and "
                       "the imaging question are fine.",
        "choices": [
            ("The patient's medical record number", True),
            ("The patient's date of birth", True),
            ("The patient's email or phone number", True),
            ("The general clinical question, with no identifiers", False),
        ],
    },
    {
        "prompt": "An AI tool returns a finding at 0.58 confidence, below your institution's "
                  "0.70 threshold. What is the correct action?",
        "kind": "single",
        "explanation": "Below-threshold output is flagged as uncertain and escalated. It is not "
                       "a result to act on, and it is not something to quietly discard either.",
        "choices": [
            ("Treat it as uncertain and escalate for human review", True),
            ("Act on it, since the model still identified something", False),
            ("Ignore it entirely and move on", False),
            ("Re-run until the confidence rises", False),
        ],
    },
    {
        "prompt": "An AI-assisted decision contributes to patient harm. Who is accountable?",
        "kind": "single",
        "explanation": "The clinician who acted, alongside the institution that deployed the "
                       "tool. A model cannot hold responsibility, and 'the algorithm said so' "
                       "has never been a defence.",
        "choices": [
            ("The clinician who acted, and the deploying institution", True),
            ("The model vendor alone", False),
            ("Nobody, since the AI made the error", False),
            ("The regulator that cleared the device", False),
        ],
    },
    {
        "prompt": "What does FDA 510(k) clearance of an imaging AI tool establish?",
        "kind": "single",
        "explanation": "Substantial equivalence to an existing marketed device. It is not "
                       "evidence that patient outcomes improve — that needs prospective trials, "
                       "which most cleared imaging AI does not have.",
        "choices": [
            ("That it is substantially equivalent to an existing device", True),
            ("That trials showed it improves patient outcomes", False),
            ("That it is safe for any imaging task", False),
            ("That its training data was externally validated", False),
        ],
    },
    {
        "prompt": "A model performed well at the hospital where it was trained and much worse "
                  "elsewhere. What is the most likely explanation?",
        "kind": "single",
        "explanation": "Dataset shift, often via shortcut learning — the model latched onto "
                       "something site-specific, like a portable film marker, that correlated "
                       "with the label locally and not elsewhere.",
        "choices": [
            ("Dataset shift, likely from a site-specific shortcut", True),
            ("The other hospitals used it incorrectly", False),
            ("The model needs more training epochs", False),
            ("Random variation between sites", False),
        ],
    },
    {
        "prompt": "Before AI-assisted analysis runs on this platform, what must happen first?",
        "kind": "single",
        "explanation": "You record your own interpretation. The server returns 409 if you try to "
                       "run the model first — the sequencing is enforced, not advisory.",
        "choices": [
            ("The student records their own reading of the image", True),
            ("The instructor approves the case", False),
            ("The image is uploaded in DICOM format", False),
            ("The model confidence threshold is raised", False),
        ],
    },
    {
        "prompt": "A model reports excellent overall accuracy but performance was never broken "
                  "down by patient subgroup. What should you conclude?",
        "kind": "single",
        "explanation": "Aggregate numbers hide subgroup failure. If it was not reported "
                       "separately, assume it was not measured — and that the tool may perform "
                       "materially worse for some of the people you will use it on.",
        "choices": [
            ("Subgroup performance is unknown and may be materially worse", True),
            ("It performs equally well across all groups", False),
            ("Subgroup analysis is unnecessary if overall accuracy is high", False),
            ("The aggregate figure covers all populations", False),
        ],
    },
]


FOUNDATIONS_QUESTIONS = [
    {
        "prompt": "What does a medical imaging classifier actually output?",
        "kind": "single",
        "explanation": "A probability over labels it was trained on. Converting that into a "
                       "diagnosis is a human act with human responsibility attached.",
        "choices": [
            ("A probability over the labels it was trained on", True),
            ("A diagnosis", False),
            ("A treatment recommendation", False),
            ("A measure of how ill the patient is", False),
        ],
    },
    {
        "prompt": "Why do most deployed imaging models struggle with genuinely unfamiliar input?",
        "kind": "single",
        "explanation": "They have no mechanism to abstain. The architecture returns a "
                       "distribution over known labels whatever it is shown.",
        "choices": [
            ("They have no way to say 'I have not seen this before'", True),
            ("They run out of memory", False),
            ("They default to the most serious diagnosis", False),
            ("They refuse to return a result", False),
        ],
    },
    {
        "prompt": "Which factors can trigger dataset shift? Select all that apply.",
        "kind": "multi",
        "explanation": "All of these change the input distribution relative to training data, "
                       "and each can degrade performance silently.",
        "choices": [
            ("A scanner or equipment upgrade", True),
            ("A different patient population", True),
            ("A change in imaging protocol", True),
            ("Renaming the model version", False),
        ],
    },
]


def _seed_courses(session: Session) -> None:
    for spec in COURSES:
        existing = session.exec(select(Course).where(Course.slug == spec["slug"])).first()
        if existing:
            continue
        course = Course(
            slug=str(spec["slug"]),
            title=str(spec["title"]),
            summary=str(spec["summary"]),
            track=str(spec["track"]),
            level=str(spec["level"]),
            emoji=str(spec["emoji"]),
            duration_minutes=int(spec["duration_minutes"]),
            order=int(spec["order"]),
            is_certification=bool(spec.get("is_certification", False)),
        )
        session.add(course)
        session.commit()
        session.refresh(course)

        lessons = spec["lessons"]
        assert isinstance(lessons, list)
        for index, lesson_spec in enumerate(lessons):
            session.add(
                Lesson(
                    course_id=course.id or 0,
                    order=index,
                    title=str(lesson_spec["title"]),
                    kind=lesson_spec["kind"],
                    duration_minutes=int(lesson_spec["duration_minutes"]),
                    key_point=str(lesson_spec.get("key_point") or "") or None,
                    body_md=str(lesson_spec["body_md"]),
                )
            )
        session.commit()


def _seed_quiz(
    session: Session, course_slug: str, title: str, description: str,
    specs: List[dict], is_certification: bool, passing_score: int,
) -> None:
    course = session.exec(select(Course).where(Course.slug == course_slug)).first()
    if not course:
        return
    existing = session.exec(select(Quiz).where(Quiz.course_id == course.id, Quiz.title == title)).first()
    if existing:
        return

    quiz = Quiz(
        course_id=course.id or 0,
        title=title,
        description=description,
        passing_score=passing_score,
        is_certification=is_certification,
    )
    session.add(quiz)
    session.commit()
    session.refresh(quiz)

    for index, spec in enumerate(specs):
        question = Question(
            quiz_id=quiz.id or 0,
            order=index,
            prompt=str(spec["prompt"]),
            kind=str(spec["kind"]),
            explanation=str(spec["explanation"]),
        )
        session.add(question)
        session.commit()
        session.refresh(question)
        for choice_index, (text, correct) in enumerate(spec["choices"]):
            session.add(
                Choice(
                    question_id=question.id or 0,
                    order=choice_index,
                    text=text,
                    is_correct=correct,
                )
            )
    session.commit()


def _seed_users(session: Session) -> List[User]:
    people = [
        ("student@medly.dev", "Alex Johnson", Role.STUDENT, "Columbia University", 3, False),
        ("certified@medly.dev", "Priya Nair", Role.STUDENT, "Columbia University", 4, True),
        ("instructor@medly.dev", "Dr. Sarah Chen", Role.INSTRUCTOR, "Columbia University", None, True),
        ("admin@medly.dev", "Medly Admin", Role.ADMIN, "Medly", None, True),
    ]
    created: List[User] = []
    for email, name, role, institution, year, certified in people:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            created.append(existing)
            continue
        user = User(
            email=email,
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name=name,
            role=role,
            institution=institution,
            year_of_study=year,
            certified=certified,
            certified_at=datetime.utcnow() if certified else None,
            competency_score=90 if certified else 0,
        )
        session.add(user)
        created.append(user)
    session.commit()
    for user in created:
        session.refresh(user)
    return created


def _seed_demo_activity(session: Session, users: List[User]) -> None:
    """A little history so the governance dashboard is not empty on first load."""
    if session.exec(select(AuditEvent)).first():
        return

    students = [u for u in users if u.role == Role.STUDENT]
    if not students:
        return

    now = datetime.utcnow()
    samples = [
        (EventType.ASSISTANT_QUERY, RiskLevel.LOW, False, None, 0.0, False),
        (EventType.ASSISTANT_QUERY, RiskLevel.MEDIUM, False, None, 0.0, False),
        (EventType.ASSISTANT_BLOCKED, RiskLevel.HIGH, True, None, 0.0, True),
        (EventType.ANALYSIS_RETURNED, RiskLevel.MEDIUM, False, None, 0.91, False),
        (EventType.ANALYSIS_ACCEPTED, RiskLevel.MEDIUM, False, False, 0.91, False),
        (EventType.ANALYSIS_RETURNED, RiskLevel.HIGH, False, None, 0.58, True),
        (EventType.ANALYSIS_OVERRIDDEN, RiskLevel.MEDIUM, False, True, 0.58, False),
        (EventType.QUIZ_SUBMITTED, RiskLevel.NONE, False, None, 0.0, False),
    ]

    for day in range(9, -1, -1):
        for index, (event_type, risk, blocked, overridden, confidence, review) in enumerate(samples):
            if (day + index) % 3 == 0:
                continue
            user = students[(day + index) % len(students)]
            session.add(
                AuditEvent(
                    created_at=now - timedelta(days=day, hours=index),
                    user_id=user.id,
                    event_type=event_type,
                    risk_level=risk,
                    ai_model="medly-sim-cxr" if "analysis" in event_type.value else "rules",
                    ai_version="0.3.0-simulated",
                    ai_output_summary="Seeded demo event",
                    confidence=confidence or None,
                    overridden=overridden,
                    blocked=blocked,
                    block_reason="Request asks for a definitive diagnosis" if blocked else None,
                    requires_review=review,
                    disclaimer_shown=True,
                    meta_json="{}",
                )
            )
    session.commit()


def _seed_progress(session: Session, users: List[User]) -> None:
    student = next((u for u in users if u.email == "certified@medly.dev"), None)
    if not student:
        return
    if session.exec(select(Enrollment).where(Enrollment.user_id == student.id)).first():
        return

    courses = session.exec(select(Course)).all()
    for course in courses[:2]:
        session.add(Enrollment(user_id=student.id or 0, course_id=course.id or 0))
    session.commit()

    first = courses[0] if courses else None
    if first:
        lessons = session.exec(select(Lesson).where(Lesson.course_id == first.id)).all()
        for lesson in lessons[:2]:
            session.add(
                LessonProgress(
                    user_id=student.id or 0,
                    lesson_id=lesson.id or 0,
                    status=ProgressStatus.COMPLETED,
                    completed_at=datetime.utcnow(),
                )
            )
        session.commit()


def run() -> None:
    init_db()
    with Session(engine) as session:
        _seed_courses(session)
        _seed_quiz(
            session,
            "ai-safety-and-ethics-certification",
            "AI Safety & Ethics Certification Exam",
            "Pass with 80% or above to unlock AI-assisted imaging analysis.",
            CERT_QUESTIONS,
            is_certification=True,
            passing_score=80,
        )
        _seed_quiz(
            session,
            "ai-in-medicine-foundations",
            "Foundations Knowledge Check",
            "A short check on the core concepts.",
            FOUNDATIONS_QUESTIONS,
            is_certification=False,
            passing_score=60,
        )
        users = _seed_users(session)
        _seed_progress(session, users)
        _seed_demo_activity(session, users)

    print("Seed complete.")
    print(f"  student@medly.dev    / {DEMO_PASSWORD}   (not certified — AI locked)")
    print(f"  certified@medly.dev  / {DEMO_PASSWORD}   (certified — AI unlocked)")
    print(f"  instructor@medly.dev / {DEMO_PASSWORD}   (sees all audit data)")
    print(f"  admin@medly.dev      / {DEMO_PASSWORD}")


if __name__ == "__main__":
    run()
