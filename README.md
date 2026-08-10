# Medly API

Backend for a platform that teaches medical students to use AI safely — and refuses
to let them use it unsafely.

FastAPI · SQLModel · SQLite (Postgres by changing one environment variable).

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed                                     # curriculum + demo accounts
uvicorn app.main:app --reload
```

Interactive docs: <http://localhost:8000/docs>

```bash
pytest -q     # 40+ tests, mostly on the guardrails
```

### Demo accounts — password `medly1234`

| Email | Why it exists |
|---|---|
| `student@medly.dev` | Not certified. AI-assisted analysis returns 403. |
| `certified@medly.dev` | Certified. The full workflow is available. |
| `instructor@medly.dev` | Sees every user's audit trail, can clear reviews. |
| `admin@medly.dev` | Full access. |

## The idea

The problem statement: AI is already reading X-rays and CTs, medical curricula do
not teach it, and no agreed safety standard governs its use. The result is
unexamined trust in tools nobody was trained to question.

So the standard is written as code, not as a policy document. Six rules, each with
the function that enforces it:

| | Rule | Enforced by |
|---|---|---|
| **S1** | Teaching only — never diagnose, treat or dose a real patient | `safety.screen_message` |
| **S2** | No patient identifiers reach a model, ever | `safety.screen_message` + `safety.redact` |
| **S3** | Every AI output is labelled and carries its limitations | `safety.apply_disclaimer` |
| **S4** | Confidence is always shown; below threshold escalates | `safety.evaluate_confidence` |
| **S5** | A named human commits a decision, and it is logged | `AnalysisJob.student_finding` + `audit_events` |
| **S6** | AI-assisted analysis stays locked until certification | `security.require_certified` |

`GET /api/governance/standard` returns this list at runtime, so the UI renders the
same rules the server enforces. They cannot drift apart.

## The anti-automation-bias workflow

Automation bias is the reason this project exists, so the API enforces the order
rather than suggesting it:

```
POST /api/analysis/cases             create the case
POST /api/analysis/{id}/my-reading   your interpretation, before any AI output
POST /api/analysis/{id}/analyze      the model runs — 409 if you skipped step 2
POST /api/analysis/{id}/decide       your final call, and whether you agreed
```

Step 4 produces the metric the governance dashboard leads with: **override rate**.
A cohort that never disagrees with the model is not reading images, and that shows
up as a number an instructor can act on.

Roughly one simulated case in four is deliberately low-confidence, so students meet
the uncertain path during training rather than for the first time on a ward.

## Swapping in real components

Both AI surfaces sit behind an interface with a working default, so nothing needs
an API key to demo.

**Assistant** — `MEDLY_ASSISTANT_PROVIDER=rules|anthropic|openai`. The `rules`
provider is offline and curriculum-aware. The others need the matching key and
package. Whichever you choose, output still passes through the guardrails; a
provider cannot opt out of the disclaimer or the audit log.

**Imaging** — `MEDLY_INFERENCE_ENGINE=mock|onnx`. The mock engine is deterministic
per case reference, so a demo behaves identically every run. To use a real model,
implement `InferenceEngine.analyze` in `app/services/inference.py`. Nothing else
changes.

The shipped engine is **simulated and uses no real patient data**. It is a training
apparatus, not a diagnostic device, and the disclaimer on every output says so.

## API surface

```
POST   /api/auth/register                 create a student account
POST   /api/auth/login                    OAuth2 password form -> JWT
GET    /api/auth/me

GET    /api/courses                       with per-user progress
GET    /api/courses/{slug}
POST   /api/courses/{slug}/enroll
GET    /api/courses/lessons/{id}
POST   /api/courses/lessons/{id}/complete

GET    /api/quizzes/course/{slug}         correct answers never serialised
GET    /api/quizzes/{id}
POST   /api/quizzes/{id}/submit           grades, and certifies on a pass
GET    /api/quizzes/attempts/me

POST   /api/assistant/chat                guardrails -> answer -> disclaimer -> log
GET    /api/assistant/history/{session}   stored redacted
GET    /api/assistant/suggestions

POST   /api/analysis/cases                        certified users only for /analyze
POST   /api/analysis/{id}/my-reading
POST   /api/analysis/{id}/analyze
POST   /api/analysis/{id}/decide
GET    /api/analysis/cases

GET    /api/governance/standard           the six rules
GET    /api/governance/audit              students see their own; staff see all
GET    /api/governance/summary            override rate, block rate, coverage
GET    /api/governance/timeseries
POST   /api/governance/audit/{id}/review  instructor/admin only
```

## Layout

```
app/
  config.py          environment settings, thresholds, the disclaimer text
  db.py              engine and session
  security.py        hashing, JWT, role deps, require_certified
  models/            User, Course, Lesson, Quiz, AuditEvent, AnalysisJob, …
  services/
    safety.py        the guardrails — the most important file here
    inference.py     InferenceEngine interface + deterministic mock
    assistant.py     provider interface + offline knowledge base
    audit.py         the single writer for audit rows
    scoring.py       grading and competency bands
  routers/           auth, courses, quizzes, assistant, analysis, governance
  seed.py            curriculum, certification exam, demo accounts
tests/               guardrails, auth, quizzes, workflow ordering, governance
```

## Moving to Postgres

```bash
MEDLY_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/medly
```

Nothing else changes. Add Alembic if you need migrations; `create_all` is fine for
a hackathon but will not carry you through schema changes in production.
