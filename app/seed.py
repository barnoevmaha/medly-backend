"""Seed the database with the curriculum and demo accounts.

    python -m app.seed
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from sqlmodel import Session, select

from app import seed_content, seed_virtual_patient
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
        "icon": "brain",
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
        "slug": "ai-safety-and-ethics",
        "title": "AI Safety & Ethics",
        "summary": "How medical AI fails, who is accountable, and what has to be recorded.",
        "track": "safety",
        "level": "core",
        "icon": "shield-check",
        "duration_minutes": 60,
        "order": 2,
        "lessons": [
            {
                "title": "Introduction to AI safety in healthcare",
                "kind": LessonKind.READING,
                "duration_minutes": 10,
                "key_point": "Safety is not a property of the model. It is a property of the "
                             "system the model sits inside — including you.",
                "body_md": (
                    "## Why a certification, and why before you touch the tool\n\n"
                    "Medical AI does not fail the way a drug fails. A drug with a safety "
                    "problem tends to produce a signal that looks like a safety problem. A "
                    "model with a safety problem produces confident, plausible output that "
                    "looks exactly like its correct output. The failure mode is silent, and it "
                    "is absorbed by whoever is holding the decision — which is you.\n\n"
                    "That is the reason this module gates the AI-assisted workbench rather "
                    "than sitting alongside it as optional reading.\n\n"
                    "## Four questions this course answers\n\n"
                    "1. **Where does the error come from?** Not from the model alone: from the "
                    "interaction between the model, the data it was trained on, the workflow "
                    "it is dropped into, and the human reading its output.\n"
                    "2. **Who is accountable?** Always a named clinician. No regulator, "
                    "insurer or court has ever accepted \"the algorithm said so\".\n"
                    "3. **What has to be recorded?** Enough that someone reconstructing the "
                    "decision six months later can see what the model said, what you did, and "
                    "whether you disagreed.\n"
                    "4. **When do you stop?** Every model has an operating envelope. Knowing "
                    "its edge is more useful than knowing its accuracy.\n\n"
                    "## The shape of the rest of this course\n\n"
                    "Automation bias, then fairness across populations, then privacy, then "
                    "calibration and uncertainty, then transparency, then the ethical and "
                    "regulatory frame. Each lesson ends where the next begins.\n\n"
                    "> Nothing here is about distrusting AI. Reflexive distrust is as "
                    "unhelpful as reflexive trust, and it costs patients the benefit. The "
                    "goal is calibrated use: knowing precisely how much weight a given output "
                    "can carry."
                ),
            },
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
                "title": "Bias and fairness across patient populations",
                "kind": LessonKind.READING,
                "duration_minutes": 13,
                "key_point": "A model is only as representative as its training set. Aggregate "
                             "accuracy hides the subgroup where it fails.",
                "body_md": (
                    "## Where the bias enters\n\n"
                    "Not from malice, and rarely from the algorithm. It enters through the "
                    "data:\n\n"
                    "- **Sampling.** Chest radiograph datasets are dominated by a handful of "
                    "large academic centres in a small number of countries. Skin lesion "
                    "datasets are overwhelmingly light-skinned.\n"
                    "- **Label bias.** If the ground truth is \"what the reporting radiologist "
                    "wrote\", the model learns that radiologist's blind spots as if they were "
                    "the disease.\n"
                    "- **Proxy variables.** A famous US care-management algorithm used prior "
                    "healthcare *spend* as a proxy for healthcare *need*. Because less money "
                    "had historically been spent on Black patients at equal illness, the model "
                    "systematically underrated their need. The algorithm never saw race. It "
                    "did not have to.\n\n"
                    "## Aggregate accuracy is not a safety claim\n\n"
                    "A model reported at 94% can be 96% in the majority group and 71% in a "
                    "subgroup that makes up 6% of the test set. The headline number is "
                    "arithmetically true and clinically useless. Always ask for performance "
                    "*stratified* by age, sex, ethnicity, scanner, and site.\n\n"
                    "## What you can do at the point of use\n\n"
                    "1. Ask which population the model was validated on, and whether your "
                    "patient resembles it.\n"
                    "2. Treat an out-of-distribution patient as a reason to weight the model "
                    "lower, not as a reason to discard your own read.\n"
                    "3. Report the misses. A subgroup failure is invisible until somebody "
                    "writes it down.\n\n"
                    "> Fairness is not a checkbox at procurement. It is a monitoring "
                    "commitment that continues for as long as the tool is deployed."
                ),
            },
            {
                "title": "Patient privacy and de-identification",
                "kind": LessonKind.READING,
                "duration_minutes": 12,
                "key_point": "Removing the name is the easy half. Images identify people "
                             "through pixels, headers and rarity.",
                "body_md": (
                    "## Three places identity hides in a scan\n\n"
                    "1. **DICOM headers.** `PatientName`, `PatientID`, `PatientBirthDate`, "
                    "`AccessionNumber`, `InstitutionName`, plus private vendor tags that vary "
                    "by scanner and are frequently missed by naive scripts.\n"
                    "2. **Burned-in pixel text.** Ultrasound and portable radiographs often "
                    "carry the name and MRN rendered into the image itself. Header scrubbing "
                    "does nothing to this.\n"
                    "3. **The anatomy.** A head CT can be volume-rendered back into a "
                    "recognisable face. Unusual implants, surgical hardware and rare anatomy "
                    "are identifying on their own.\n\n"
                    "## De-identified is not anonymous\n\n"
                    "Removing direct identifiers reduces risk; it does not eliminate "
                    "re-identification. Linking a small number of quasi-identifiers — postcode, "
                    "date of birth, sex, rare diagnosis — has repeatedly been shown to be enough "
                    "to name individuals. Treat de-identified imaging as *lower risk*, never as "
                    "*no risk*.\n\n"
                    "## Automated redaction, and why it is never the last step\n\n"
                    "Automatic tools are good at removing what they can name and bad at knowing "
                    "what they missed. A pattern matcher that finds nothing is indistinguishable "
                    "from one pointed at the wrong field. This is the same trap as automation "
                    "bias, applied to privacy.\n\n"
                    "In this platform, teacher-authored case references follow a fixed route:\n\n"
                    "```\n"
                    "Teacher -> Case reference -> Scan -> Automatic redaction -> Human "
                    "verification -> Student\n"
                    "```\n\n"
                    "The automatic pass produces a **proposal**, marked `auto_redacted`. Only a "
                    "teacher can move an image to `verified`, and no student can load an image "
                    "in any other state. The gate is in the API, not the interface.\n\n"
                    "## Minimum necessary\n\n"
                    "Teaching needs an age band, a sex, a clinical question and an image. It "
                    "does not need a date of birth, a postcode or an admission date. Every field "
                    "you carry is a field you have to defend."
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
                "title": "Transparency and explainability you can defend",
                "kind": LessonKind.READING,
                "duration_minutes": 11,
                "key_point": "An explanation you cannot check is decoration. Ask what would "
                             "have changed the answer.",
                "body_md": (
                    "## Two different things called explainability\n\n"
                    "**Interpretable by construction** — a model whose decision rule can be "
                    "read directly, like a small decision tree or a scoring system. Rare in "
                    "imaging, common and underrated in risk prediction.\n\n"
                    "**Post-hoc explanation** — a second method that attempts to describe what "
                    "an opaque model did. Saliency maps, Grad-CAM, SHAP. These are estimates "
                    "*about* the model, and they carry their own error.\n\n"
                    "## The honest reading of a heatmap\n\n"
                    "A saliency map says which pixels, when perturbed, most change the output. "
                    "It does not say the model \"looked at\" the lesion, and it does not "
                    "confirm the prediction. Published work has shown saliency maps that are "
                    "nearly unchanged when the model's own weights are randomised — an "
                    "explanation that survives destroying the thing it claims to explain is "
                    "explaining nothing.\n\n"
                    "## Questions that actually discriminate\n\n"
                    "- What is the model's intended use, in one sentence?\n"
                    "- What input would make it abstain? If the answer is \"nothing\", it has "
                    "no notion of its own limits.\n"
                    "- Which features or regions would have flipped this output?\n"
                    "- Where can I see its performance on patients like this one?\n\n"
                    "## Transparency owed to the patient\n\n"
                    "Separate from technical explainability: the patient is entitled to know "
                    "that an AI system contributed to their care, in language they can act on. "
                    "In this platform every AI output carries a disclaimer that cannot be "
                    "switched off, and every interaction is written to the audit log — "
                    "transparency as a system property, not a preference."
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
        "icon": "scan",
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


SAFETY_QUESTIONS = [
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
    """Create courses, and reconcile their lessons on every run.

    Reconciling rather than skipping matters for an already-deployed database:
    a course added lessons after launch, and a `continue` on the existing row
    would leave that install permanently on the old four-lesson version.
    Lessons are matched by title, so re-running never duplicates one.
    """
    for spec in COURSES:
        course = session.exec(select(Course).where(Course.slug == spec["slug"])).first()
        if not course:
            course = Course(
                slug=str(spec["slug"]),
                title=str(spec["title"]),
                summary=str(spec["summary"]),
                track=str(spec["track"]),
                level=str(spec["level"]),
                icon=str(spec["icon"]),
                duration_minutes=int(spec["duration_minutes"]),
                order=int(spec["order"]),
            )
            session.add(course)
            session.commit()
            session.refresh(course)

        lessons = spec["lessons"]
        assert isinstance(lessons, list)
        existing = {
            lesson.title: lesson
            for lesson in session.exec(
                select(Lesson).where(Lesson.course_id == course.id)
            ).all()
        }
        for index, lesson_spec in enumerate(lessons):
            title = str(lesson_spec["title"])
            lesson = existing.get(title)
            if lesson is None:
                lesson = Lesson(course_id=course.id or 0, title=title)
            lesson.order = index
            lesson.kind = lesson_spec["kind"]
            lesson.duration_minutes = int(lesson_spec["duration_minutes"])
            lesson.key_point = str(lesson_spec.get("key_point") or "") or None
            lesson.body_md = str(lesson_spec["body_md"])
            session.add(lesson)

        # Keep the advertised duration honest once lessons change.
        course.duration_minutes = sum(int(item["duration_minutes"]) for item in lessons)
        session.add(course)
        session.commit()


def _seed_quiz(
    session: Session, course_slug: str, title: str, description: str,
    specs: List[dict], passing_score: int,
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
    # The premium flag is deliberately split across the two student accounts so
    # both sides of the paywall can be demonstrated without editing the database.
    people = [
        ("student@medly.dev", "Alex Johnson", Role.STUDENT, "Columbia University", 3, False),
        ("premium@medly.dev", "Priya Nair", Role.STUDENT, "Columbia University", 4, True),
        ("instructor@medly.dev", "Dr. Sarah Chen", Role.INSTRUCTOR, "Columbia University", None, True),
        ("admin@medly.dev", "Medly Admin", Role.ADMIN, "Medly", None, True),
    ]
    created: List[User] = []
    for email, name, role, institution, year, premium in people:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            # A database created before the premium flag existed has every demo
            # account on the default. Reconcile so the paywall demo still works
            # after an upgrade in place, without touching anything else.
            if existing.is_premium != premium:
                existing.is_premium = premium
                session.add(existing)
                session.commit()
            created.append(existing)
            continue
        user = User(
            email=email,
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name=name,
            role=role,
            institution=institution,
            year_of_study=year,
            is_premium=premium,
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
    student = next((u for u in users if u.email == "premium@medly.dev"), None)
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


def _seed_memberships(session: Session, users: List[User]) -> None:
    """Put the demo students in a few communities so Profile → Communities has rows."""
    from app.models.community import Community, CommunityMember

    wanted = {
        "student@medly.dev": ["cardiology-club", "emergency-medicine"],
        "premium@medly.dev": ["radiology-residents", "ai-in-medicine", "internal-medicine"],
        "instructor@medly.dev": ["radiology-residents", "ai-in-medicine"],
    }
    for user in users:
        for slug in wanted.get(user.email, []):
            community = session.exec(
                select(Community).where(Community.slug == slug)
            ).first()
            if not community:
                continue
            existing = session.exec(
                select(CommunityMember).where(
                    CommunityMember.community_id == community.id,
                    CommunityMember.user_id == user.id,
                )
            ).first()
            if not existing:
                session.add(
                    CommunityMember(community_id=community.id or 0, user_id=user.id or 0)
                )
    session.commit()


def _rename_legacy_rows(session: Session) -> None:
    """Carry an existing database across the renames.

    Certification was removed, and two names went with it: the course slug and
    the demo account. Without this an upgraded install would end up with both
    the old and the new row, which is worse than either.
    """
    course = session.exec(
        select(Course).where(Course.slug == "ai-safety-and-ethics-certification")
    ).first()
    if course and not session.exec(
        select(Course).where(Course.slug == "ai-safety-and-ethics")
    ).first():
        course.slug = "ai-safety-and-ethics"
        course.title = "AI Safety & Ethics"
        session.add(course)

    old_account = session.exec(select(User).where(User.email == "certified@medly.dev")).first()
    if old_account and not session.exec(
        select(User).where(User.email == "premium@medly.dev")
    ).first():
        old_account.email = "premium@medly.dev"
        old_account.is_premium = True
        session.add(old_account)

    for quiz in session.exec(
        select(Quiz).where(Quiz.title == "AI Safety & Ethics Certification Exam")
    ).all():
        quiz.title = "AI Safety & Ethics Knowledge Check"
        quiz.description = "Twelve questions on bias, calibration, privacy and accountability."
        session.add(quiz)

    session.commit()


def run() -> None:
    init_db()
    with Session(engine) as session:
        _rename_legacy_rows(session)
        _seed_courses(session)
        _seed_quiz(
            session,
            "ai-safety-and-ethics",
            "AI Safety & Ethics Knowledge Check",
            "Twelve questions on bias, calibration, privacy and accountability.",
            SAFETY_QUESTIONS,
            passing_score=80,
        )
        _seed_quiz(
            session,
            "ai-in-medicine-foundations",
            "Foundations Knowledge Check",
            "A short check on the core concepts.",
            FOUNDATIONS_QUESTIONS,
            passing_score=60,
        )
        users = _seed_users(session)
        _seed_progress(session, users)
        _seed_demo_activity(session, users)

        # Product content: feed, library, communities, challenges, casebook.
        seed_content.run(session, users, hash_password(DEMO_PASSWORD))
        _seed_memberships(session, users)
        seed_virtual_patient.run(session)

    print("Seed complete.")
    print(f"  student@medly.dev    / {DEMO_PASSWORD}   (free student)")
    print(f"  premium@medly.dev    / {DEMO_PASSWORD}   (premium student)")
    print(f"  instructor@medly.dev / {DEMO_PASSWORD}   (teacher — authors cases)")
    print(f"  admin@medly.dev      / {DEMO_PASSWORD}")


if __name__ == "__main__":
    run()
