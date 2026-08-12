"""Medical terminology the translator must use, and the rules it must obey.

One place, so "shortness of breath" does not become three different Uzbek
phrases on three screens. A student who meets `hansirash` in a case and
`nafas qisishi` in the quiz about that case has to work out whether they are
the same complaint, which is effort spent on vocabulary rather than medicine.

Uzbek is the weak spot for every machine translator, and it is the locale most
of these students actually read. The Uzbek column here is the authored answer,
not a suggestion — `medical_translate` puts it in the prompt and rejects
output that ignores it.

Adding a term is the whole edit: nothing else needs to change, and existing
cached translations are unaffected until they are cleared and re-run.
"""
from __future__ import annotations

from typing import Dict

SUPPORTED = ("ru", "uz")

# Written the same way in all three languages, so a translation that changes
# them has made a mistake. Deliberately short.
#
# Units and clinical abbreviations are NOT here, though the first draft of
# this file had them. "mg" is "мг" in Russian and "CT" is "КТ"; forcing the
# Latin form would produce text no Russian clinician would write, and the
# validator would have rejected every correct translation of a dose. They live
# in TERMS below with their proper rendering per language instead — the same
# mistake, and the same fix, as protecting a word that should be translated.
DO_NOT_TRANSLATE = (
    "Medly",
    "CURB-65",
    "SpO₂",
    "SpO2",
    "pH",
)

# English term -> required rendering. Lower-cased keys; matching is
# case-insensitive and the renderings are given in their natural case.
TERMS: Dict[str, Dict[str, str]] = {
    # --- presentation and symptoms ---------------------------------------
    "shortness of breath": {"ru": "одышка", "uz": "nafas qisishi"},
    "breathlessness": {"ru": "одышка", "uz": "nafas qisishi"},
    "confusion": {"ru": "спутанность сознания", "uz": "ong chalkashligi"},
    "chest pain": {"ru": "боль в грудной клетке", "uz": "koʻkrak qafasidagi ogʻriq"},
    "cough": {"ru": "кашель", "uz": "yoʻtal"},
    "sputum": {"ru": "мокрота", "uz": "balgʻam"},
    "fever": {"ru": "лихорадка", "uz": "isitma"},
    "chills": {"ru": "озноб", "uz": "titroq"},
    "fatigue": {"ru": "утомляемость", "uz": "holsizlik"},
    "nausea": {"ru": "тошнота", "uz": "koʻngil aynishi"},
    "vomiting": {"ru": "рвота", "uz": "qusish"},
    "dizziness": {"ru": "головокружение", "uz": "bosh aylanishi"},
    "palpitations": {"ru": "сердцебиение", "uz": "yurak urishi"},
    "wheeze": {"ru": "свистящее дыхание", "uz": "hushtaksimon nafas"},
    "crackles": {"ru": "хрипы", "uz": "xirillash"},
    "oedema": {"ru": "отёк", "uz": "shish"},
    "edema": {"ru": "отёк", "uz": "shish"},
    "rash": {"ru": "сыпь", "uz": "toshma"},
    "pain": {"ru": "боль", "uz": "ogʻriq"},
    # --- observations and vitals -----------------------------------------
    "vital signs": {"ru": "жизненные показатели", "uz": "hayotiy koʻrsatkichlar"},
    "vitals": {"ru": "жизненные показатели", "uz": "hayotiy koʻrsatkichlar"},
    "heart rate": {"ru": "частота сердечных сокращений", "uz": "yurak urishi tezligi"},
    "respiratory rate": {"ru": "частота дыхания", "uz": "nafas olish tezligi"},
    "blood pressure": {"ru": "артериальное давление", "uz": "arterial bosim"},
    "temperature": {"ru": "температура", "uz": "harorat"},
    "oxygen saturation": {"ru": "сатурация кислорода", "uz": "kislorod saturatsiyasi"},
    "consciousness": {"ru": "сознание", "uz": "ong"},
    # --- assessment -------------------------------------------------------
    "history": {"ru": "анамнез", "uz": "anamnez"},
    "medical history": {"ru": "анамнез", "uz": "anamnez"},
    "past medical history": {"ru": "анамнез жизни", "uz": "hayot anamnezi"},
    "examination": {"ru": "осмотр", "uz": "koʻrik"},
    "physical examination": {"ru": "физикальный осмотр", "uz": "fizikal koʻrik"},
    "auscultation": {"ru": "аускультация", "uz": "auskultatsiya"},
    "investigation": {"ru": "исследование", "uz": "tekshiruv"},
    "chest x-ray": {"ru": "рентгенография грудной клетки", "uz": "koʻkrak qafasi rentgeni"},
    "blood test": {"ru": "анализ крови", "uz": "qon tahlili"},
    "blood culture": {"ru": "посев крови", "uz": "qon ekmasi"},
    "lactate": {"ru": "лактат", "uz": "laktat"},
    "white cell count": {"ru": "количество лейкоцитов", "uz": "leykotsitlar soni"},
    # --- diagnosis and conditions ----------------------------------------
    "diagnosis": {"ru": "диагноз", "uz": "tashxis"},
    "differential diagnosis": {
        "ru": "дифференциальный диагноз",
        "uz": "differensial tashxis",
    },
    "pneumonia": {"ru": "пневмония", "uz": "pnevmoniya"},
    "community-acquired pneumonia": {
        "ru": "внебольничная пневмония",
        "uz": "jamoada orttirilgan pnevmoniya",
    },
    "sepsis": {"ru": "сепсис", "uz": "sepsis"},
    "septic shock": {"ru": "септический шок", "uz": "septik shok"},
    "heart failure": {"ru": "сердечная недостаточность", "uz": "yurak yetishmovchiligi"},
    "myocardial infarction": {"ru": "инфаркт миокарда", "uz": "miokard infarkti"},
    "pulmonary embolism": {"ru": "тромбоэмболия лёгочной артерии", "uz": "oʻpka emboliyasi"},
    "asthma": {"ru": "астма", "uz": "astma"},
    "diabetes": {"ru": "сахарный диабет", "uz": "qandli diabet"},
    "hypertension": {"ru": "артериальная гипертензия", "uz": "arterial gipertenziya"},
    "stroke": {"ru": "инсульт", "uz": "insult"},
    "dehydration": {"ru": "обезвоживание", "uz": "suvsizlanish"},
    "infection": {"ru": "инфекция", "uz": "infeksiya"},
    # --- management -------------------------------------------------------
    "treatment": {"ru": "лечение", "uz": "davolash"},
    "management": {"ru": "тактика ведения", "uz": "olib borish taktikasi"},
    "antibiotics": {"ru": "антибиотики", "uz": "antibiotiklar"},
    "oxygen therapy": {"ru": "кислородная терапия", "uz": "kislorod terapiyasi"},
    "fluid resuscitation": {"ru": "инфузионная терапия", "uz": "infuzion terapiya"},
    "escalate": {"ru": "эскалация помощи", "uz": "yordam darajasini oshirish"},
    "discharge": {"ru": "выписка", "uz": "chiqarish"},
    "admission": {"ru": "госпитализация", "uz": "gospitalizatsiya"},
    "referral": {"ru": "направление", "uz": "yoʻllanma"},
    "monitoring": {"ru": "наблюдение", "uz": "kuzatuv"},
    "dose": {"ru": "доза", "uz": "doza"},
    # --- people and places -------------------------------------------------
    "patient": {"ru": "пациент", "uz": "bemor"},
    "clinician": {"ru": "врач", "uz": "shifokor"},
    "nurse": {"ru": "медсестра", "uz": "hamshira"},
    "emergency department": {
        "ru": "отделение неотложной помощи",
        "uz": "shoshilinch tibbiy yordam boʻlimi",
    },
    "ward": {"ru": "отделение", "uz": "boʻlim"},
    "intensive care": {"ru": "интенсивная терапия", "uz": "intensiv terapiya"},
    # --- units and abbreviations ------------------------------------------
    # Russian transliterates these; Uzbek generally keeps the Latin form.
    # Listed so the translator is told the right rendering rather than being
    # forbidden from changing them at all.
    "mg": {"ru": "мг", "uz": "mg"},
    "mcg": {"ru": "мкг", "uz": "mkg"},
    "mL": {"ru": "мл", "uz": "ml"},
    "kg": {"ru": "кг", "uz": "kg"},
    "mmHg": {"ru": "мм рт. ст.", "uz": "mm Hg"},
    "bpm": {"ru": "уд/мин", "uz": "zarba/daqiqa"},
    "ECG": {"ru": "ЭКГ", "uz": "EKG"},
    "CT": {"ru": "КТ", "uz": "KT"},
    "MRI": {"ru": "МРТ", "uz": "MRT"},
    "ICU": {"ru": "ОРИТ", "uz": "intensiv terapiya boʻlimi"},
    "GCS": {"ru": "шкала комы Глазго", "uz": "Glazgo koma shkalasi"},
    "COPD": {
        "ru": "ХОБЛ",
        "uz": "surunkali obstruktiv oʻpka kasalligi",
    },
    "CRP": {"ru": "С-реактивный белок", "uz": "C-reaktiv oqsil"},
    "intravenous": {"ru": "внутривенно", "uz": "vena ichiga"},
    "intramuscular": {"ru": "внутримышечно", "uz": "mushak ichiga"},
    "oral": {"ru": "перорально", "uz": "ogʻiz orqali"},
    # --- teaching vocabulary ----------------------------------------------
    "clinical reasoning": {"ru": "клиническое мышление", "uz": "klinik fikrlash"},
    "patient safety": {"ru": "безопасность пациента", "uz": "bemor xavfsizligi"},
    "automation bias": {
        "ru": "предвзятость к автоматизации",
        "uz": "avtomatlashtirishga moyillik",
    },
    "learning objective": {"ru": "цель обучения", "uz": "oʻquv maqsadi"},
    "case": {"ru": "клинический случай", "uz": "klinik holat"},
    "debrief": {"ru": "разбор случая", "uz": "holat tahlili"},
}

TONE = {
    "ru": (
        "Formal medical Russian as used in a teaching hospital. Address the "
        "student with «вы», lowercase. Use accepted clinical vocabulary, not "
        "colloquial paraphrase."
    ),
    "uz": (
        "Latin-script Uzbek with correct orthography: oʻ and gʻ use U+02BB, "
        "the glottal stop uses U+02BC (maʼlumot, taʼlim). Address the student "
        "with the polite «siz». Prefer established Uzbek clinical vocabulary; "
        "where a term is an international loanword in Uzbek medical practice "
        "(pnevmoniya, sepsis, diagnoz), use the loanword rather than inventing "
        "a calque."
    ),
}


def terms_for(target: str, text: str) -> Dict[str, str]:
    """Glossary entries that actually occur in `text`.

    Sending all 90 terms with every request would spend most of the prompt on
    vocabulary the passage never uses, so only the relevant ones go.
    """
    haystack = text.lower()
    return {
        term: rendering[target]
        for term, rendering in TERMS.items()
        if target in rendering and term in haystack
    }


def prompt_section(target: str, text: str) -> str:
    """The glossary block for a translation prompt, or '' if nothing applies."""
    found = terms_for(target, text)
    if not found:
        return ""
    lines = "\n".join(f"  {term} -> {rendering}" for term, rendering in sorted(found.items()))
    return f"REQUIRED TERMINOLOGY (use exactly these renderings):\n{lines}"
