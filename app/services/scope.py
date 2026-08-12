"""Topic boundary for Medly AI.

Runs before Gemini, never after. An out-of-scope question is refused from this
process — no upstream request, no tokens spent, no latency.

The hard part is not rejecting "what is Python". It is rejecting that while
still accepting "what are the main causes?", which is a legitimate medical
follow-up containing no medical word at all. So the decision uses four signals
rather than a single keyword match:

    1. an override attempt          -> refuse
    2. an explicitly off-topic term -> refuse   (beats every allow below)
    3. a medical/curriculum term    -> allow
    4. the page the user is on      -> allow    (article, challenge, resource)
    5. a referential follow-up in a conversation already under way -> allow
       (short, and either pronoun-led or a bare interrogative — a deliberate
       widening, because refusing "what are the main causes?" mid-topic would
       be a worse bug than the occasional off-topic short question that the
       deny list happens not to name)
    6. nothing at all               -> refuse

Order matters. The deny list is checked before the continuation rule, or
"now write me a React component" would ride in on the back of a medical
conversation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

# Authored per locale, not machine-translated. This is the one sentence a
# student sees when the assistant declines, it never varies, and a refusal
# arriving in English to someone reading Russian reads as a system that does
# not know who it is talking to.
REFUSAL_BY_LANG = {
    "en": (
        "I'm Medly AI, a medical learning assistant. I can only help with medical "
        "education, medical topics, and Medly learning materials."
    ),
    "ru": (
        "Я Medly AI, помощник по медицинскому обучению. Я могу помочь только с "
        "медицинским образованием, медицинскими темами и учебными материалами Medly."
    ),
    "uz": (
        "Men Medly AI — tibbiy taʼlim yordamchisiman. Men faqat tibbiy taʼlim, "
        "tibbiy mavzular va Medly oʻquv materiallari boʻyicha yordam bera olaman."
    ),
}

# The English wording, kept under its original name: it is asserted verbatim
# in tests and referenced elsewhere.
REFUSAL = REFUSAL_BY_LANG["en"]


def refusal_for(lang: str) -> str:
    return REFUSAL_BY_LANG.get(lang, REFUSAL)


def _words(*groups: Iterable[str]) -> re.Pattern:
    """One word-boundary alternation over every term given."""
    terms = sorted({t for group in groups for t in group}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in terms) + r")(?!\w)", re.I)


# --------------------------------------------------------------------------
# 1. Attempts to replace the system instruction
# --------------------------------------------------------------------------

INJECTION_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"ignore (all |any |the )?(previous|prior|earlier|above)\s+(instruction|prompt|rule|message)",
        r"disregard (all |any |the )?(previous|prior|earlier|above)",
        r"forget (that )?(you are|you're|your|everything|all)",
        r"you are (now|no longer)\b",
        r"you're (now|no longer)\b",
        r"pretend (to be|you are|you're)",
        r"act as (a|an|if)\b",
        r"from now on,? (you|answer|respond)",
        r"\bnew (system )?(instruction|prompt)s?\b",
        r"(system|developer) (prompt|instruction|message)",
        r"answer (everything|anything|all questions)",
        r"(without|no) (restriction|limitation|filter|guardrail)s?",
        r"\bjailbreak\b|\bDAN mode\b|\bdeveloper mode\b",
        r"stop being\b",
        r"override your\b",
    )
]

# --------------------------------------------------------------------------
# 2. Explicitly outside medical education
# --------------------------------------------------------------------------

OFF_TOPIC = _words(
    # programming and software
    (
        "python", "javascript", "typescript", "java", "kotlin", "swift", "golang",
        "rust", "php", "ruby", "c++", "c#", "html", "css", "sql", "react",
        "angular", "vue", "svelte", "node", "nodejs", "npm", "django", "flask",
        "fastapi", "spring boot", "api endpoint", "frontend", "backend",
        "website", "web app", "mobile app", "docker", "kubernetes", "git",
        "github", "regex", "algorithm", "compiler", "debug my code",
        "source code", "write code", "code snippet", "programming",
        "software engineer", "web development", "app development",
    ),
    # entertainment and lifestyle
    (
        "joke", "jokes", "funny story", "meme", "movie", "movies", "film",
        "netflix", "tv show", "series recommendation", "song", "music",
        "album", "video game", "gaming", "football", "soccer", "basketball",
        "recipe", "cook", "cooking", "pasta", "pizza", "restaurant",
        "horoscope", "astrology",
    ),
    # general knowledge, news, commerce
    (
        "weather", "forecast", "capital of", "population of", "president of",
        "prime minister", "election", "stock market", "crypto", "bitcoin",
        "investment advice", "flight", "hotel", "travel itinerary",
        "translate this sentence", "write an essay about",
        "homework about history", "world war", "geography",
    ),
    # named non-medical figures that come up as tests
    ("elon musk", "donald trump", "taylor swift", "cristiano ronaldo"),
)

# --------------------------------------------------------------------------
# 3. Medical education and the Medly curriculum
# --------------------------------------------------------------------------

MEDICAL = _words(
    # the discipline
    (
        "medical", "medicine", "clinical", "clinic", "patient", "doctor",
        "physician", "nurse", "nursing", "hospital", "ward", "surgery",
        "surgical", "diagnosis", "diagnostic", "differential", "prognosis",
        "treatment", "therapy", "therapeutic", "symptom", "symptoms", "sign",
        "syndrome", "disease", "disorder", "pathology", "pathophysiology",
        "aetiology", "etiology", "epidemiology", "comorbidity", "lesion",
        "infection", "inflammation", "malignancy", "tumour", "tumor", "cancer",
        "biopsy", "autopsy", "triage", "prophylaxis", "contraindication",
        "adverse effect", "side effect", "dose", "dosage", "guideline",
    ),
    # specialties
    (
        "anatomy", "physiology", "histology", "embryology", "biochemistry",
        "microbiology", "immunology", "genetics", "pharmacology", "pharmacy",
        "toxicology", "cardiology", "cardiac", "neurology", "neuro",
        "psychiatry", "psychiatric", "dermatology", "endocrinology",
        "endocrine", "gastroenterology", "gastro", "haematology", "hematology",
        "nephrology", "renal", "oncology", "ophthalmology", "orthopaedic",
        "orthopedic", "otolaryngology", "paediatric", "pediatric", "obstetric",
        "gynaecology", "gynecology", "urology", "rheumatology", "pulmonology",
        "respiratory", "anaesthesia", "anesthesia", "radiology", "radiography",
        "pathophysiological", "emergency medicine", "intensive care", "icu",
        "public health", "epidemiological",
    ),
    # body, systems, common conditions
    (
        "heart", "cardiac cycle", "lung", "lungs", "liver", "kidney", "kidneys",
        "brain", "nerve", "neuron", "muscle", "bone", "joint", "blood",
        "plasma", "artery", "vein", "capillary", "hormone", "insulin",
        "glucose", "cholesterol", "electrolyte", "antibody", "antigen",
        "bacteria", "virus", "viral", "bacterial", "fungal", "parasite",
        "diabetes", "diabetic", "hypertension", "hypotension", "asthma",
        "copd", "pneumonia", "sepsis", "stroke", "infarction", "ischaemia",
        "ischemia", "angina", "arrhythmia", "anaemia", "anemia", "leukaemia",
        "leukemia", "lymphoma", "hepatitis", "cirrhosis", "nephrotic",
        "nephritic", "ulcer", "fracture", "seizure", "epilepsy", "migraine",
        "dementia", "depression", "anxiety", "schizophrenia", "obesity",
        "malnutrition", "pregnancy", "fever", "pain", "oedema", "edema",
        "insulin resistance", "thyroid", "adrenal", "pituitary",
    ),
    # reproductive biology, genetics and sexual health
    (
        "sex", "biological sex", "sex chromosome", "sex chromosomes",
        "x chromosome", "y chromosome", "sex hormone", "sex hormones",
        "estrogen", "oestrogen", "testosterone", "progesterone", "puberty",
        "gonad", "gonads", "ovary", "ovaries", "testis", "testes", "uterus",
        "ovulation", "menstrual", "menstruation", "menopause", "gamete",
        "sperm", "fertilisation", "fertilization", "reproductive system",
        "reproductive health", "sexual development", "sex differentiation",
        "intersex", "sexually transmitted", "chlamydia", "gonorrhoea",
        "gonorrhea", "syphilis", "contraception", "contraceptive", "libido",
        "erectile", "fertility", "infertility",
    ),
    # investigations
    (
        "ecg", "ekg", "eeg", "mri", "ct scan", "x-ray", "xray", "ultrasound",
        "scan", "imaging", "radiograph", "blood test", "lab result",
        "biomarker", "culture", "histopathology", "spirometry", "auscultation",
        "palpation", "vital signs", "blood pressure",
    ),
    # drugs and classes
    (
        "drug", "medication", "antibiotic", "antibiotics", "analgesic",
        "opioid", "nsaid", "paracetamol", "acetaminophen", "ibuprofen",
        "aspirin", "statin", "beta blocker", "ace inhibitor", "diuretic",
        "anticoagulant", "corticosteroid", "steroid", "antidepressant",
        "antipsychotic", "vaccine", "vaccination", "immunisation",
        "immunization", "mechanism of action", "pharmacokinetics",
        "pharmacodynamics",
    ),
    # the Medly curriculum: safe use of AI in medicine
    (
        "automation bias", "dataset shift", "distribution shift", "calibration",
        "calibrated", "saliency", "heatmap", "grad-cam", "sensitivity",
        "specificity", "positive predictive value", "negative predictive value",
        "ppv", "npv", "false positive", "false negative", "clinical ai",
        "medical ai", "model", "explainability", "interpretability",
        "external validation", "informed consent", "anonymisation",
        "anonymization", "de-identification", "hipaa", "gdpr",
    ),
    # abbreviations students actually type
    (
        "aki", "ckd", "mi", "stemi", "nstemi", "chf", "copd", "dvt", "pe",
        "uti", "gi", "cns", "cvs", "dka", "hba1c", "bmi", "gfr", "lft", "fbc",
        "cbc", "abg", "crp", "esr", "tia", "ards", "sirs", "raas", "hpa",
        "sti", "std", "hiv", "hpv",
    ),
    # studying
    (
        "mcq", "mcqs", "exam", "osce", "usmle", "plab", "revision", "case study",
        "clinical case", "differential diagnosis", "study question",
    ),
)

# A follow-up that plainly refers back to the previous answer. Short, and
# either pronoun-led or a bare instruction — never a fresh topic.
CONTINUATION = re.compile(
    r"^\s*(?:"
    r"(?:can you |could you |please |now |and |but |so )*"
    r"(?:explain|clarify|expand|elaborate|continue|go on|more|why|how|what|which|when|where|list|name|give|show|describe|compare|define|tell me more|summarise|summarize|simplify|repeat|again|example|another)"
    r"\b.*|"
    r".*\b(?:that|this|it|these|those|them|the above|previous answer|last answer)\b.*"
    r")\s*$",
    re.I,
)
CONTINUATION_MAX_CHARS = 120


@dataclass(frozen=True)
class ScopeVerdict:
    in_scope: bool
    reason: str

    @property
    def refusal(self) -> str:
        return REFUSAL


def classify(
    message: str,
    *,
    has_page_context: bool = False,
    has_history: bool = False,
    is_quick_action: bool = False,
) -> ScopeVerdict:
    """Decide whether Medly AI should answer at all.

    `is_quick_action` is trusted because those strings are written by the
    server, not the user — see QUICK_ACTIONS in routers/assistant.py. They
    always follow an answer that was already in scope.
    """
    text = (message or "").strip()
    if not text:
        return ScopeVerdict(False, "empty")

    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return ScopeVerdict(False, "instruction override attempt")

    hit = OFF_TOPIC.search(text)
    if hit:
        return ScopeVerdict(False, f"off-topic term: {hit.group(1).lower()}")

    if is_quick_action:
        return ScopeVerdict(True, "server-authored follow-up")

    medical = MEDICAL.search(text)
    if medical:
        return ScopeVerdict(True, f"medical term: {medical.group(1).lower()}")

    if has_page_context:
        return ScopeVerdict(True, "question about the open page")

    if has_history and len(text) <= CONTINUATION_MAX_CHARS and CONTINUATION.match(text):
        return ScopeVerdict(True, "follow-up in an existing conversation")

    return ScopeVerdict(False, "no medical subject")


def find_off_topic(message: str) -> Optional[str]:
    """Exposed for logging and tests."""
    hit = OFF_TOPIC.search(message or "")
    return hit.group(1).lower() if hit else None


def medical_terms(message: str) -> List[str]:
    return [m.group(1).lower() for m in MEDICAL.finditer(message or "")]
