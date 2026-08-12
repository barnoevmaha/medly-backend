"""The safety net around machine-translated clinical text.

The interesting tests here are the rejections. A translation that reads well
and says 50 mg where the source said 5 mg is far more dangerous than one that
fails outright, and it is exactly what a general-purpose translator will
occasionally produce. `validation_error` is what stands between that and the
database, so it is tested harder than the happy path.
"""
from __future__ import annotations

import pytest

from app.services import medical_glossary as glossary
from app.services import medical_translate as mt


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

def test_identical_numbers_pass() -> None:
    assert mt.validation_error("Give 500 mg amoxicillin", "Дать 500 мг амоксициллина", "ru") is None


def test_a_changed_dose_is_rejected() -> None:
    problem = mt.validation_error("Give 5 mg", "Дать 50 мг", "ru")
    assert problem is not None and "numbers changed" in problem


def test_a_dropped_number_is_rejected() -> None:
    problem = mt.validation_error(
        "HR 118, RR 28, SpO2 89%", "ЧСС 118, ЧД 28, SpO2", "ru"
    )
    assert problem is not None and "numbers changed" in problem


def test_an_invented_number_is_rejected() -> None:
    problem = mt.validation_error("The patient is short of breath", "Пациент 74 лет", "ru")
    assert problem is not None and "numbers changed" in problem


@pytest.mark.parametrize(
    "source, translated",
    [
        # Russian writes the decimal separator as a comma. Same digits.
        ("Temperature 38.5°C", "Температура 38,5 °C"),
        # And groups thousands with a space rather than a comma.
        ("1,200 mL", "1 200 мл"),
    ],
)
def test_separator_conventions_are_not_mistaken_for_changed_numbers(
    source: str, translated: str
) -> None:
    """The check compares runs of digits, not parsed numbers.

    Parsing would read "38,5" as thirty-eight and "1 200" as two numbers, and
    reject both correct translations.
    """
    assert mt.validation_error(source, translated, "ru") is None


def test_age_survives_a_russian_construction() -> None:
    assert (
        mt.validation_error(
            "A 74-year-old man is brought to the emergency department",
            "74-летний мужчина доставлен в отделение неотложной помощи",
            "ru",
        )
        is None
    )


# --------------------------------------------------------------------------
# Everything else that must survive
# --------------------------------------------------------------------------

def test_empty_is_rejected() -> None:
    assert mt.validation_error("Shortness of breath", "", "ru") == "empty"
    assert mt.validation_error("Shortness of breath", "   ", "ru") == "empty"


def test_a_changed_placeholder_is_rejected() -> None:
    problem = mt.validation_error("Stage {n} of {total}", "Этап {n} из {всего}", "ru")
    assert problem is not None and "placeholders" in problem


def test_placeholders_may_be_reordered() -> None:
    assert mt.validation_error("{a} then {b}", "{b}, потом {a}", "ru") is None


def test_a_dropped_protected_term_is_rejected() -> None:
    problem = mt.validation_error(
        "Read the Medly guidance", "Прочитайте руководство", "ru"
    )
    assert problem is not None and "Medly" in problem


def test_a_dropped_scoring_tool_is_rejected() -> None:
    """Caught by the digit check before the term check — either is a rejection.

    CURB-65 carries a number in its name, so losing it trips the numeric guard
    first. Worth pinning: the reason in the log differs from what you might
    expect, and the value is still refused.
    """
    problem = mt.validation_error(
        "Calculate the CURB-65 score", "Рассчитайте балл тяжести", "ru"
    )
    assert problem is not None


def test_units_and_acronyms_are_allowed_to_change_script() -> None:
    """`mg` is `мг` and `CT` is `КТ`.

    Protecting these would reject every correct Russian translation of a dose
    or an imaging order — which is exactly what the first version of the
    glossary did.
    """
    assert mt.validation_error("Order a CT of the chest", "Заказать КТ грудной клетки", "ru") is None
    assert mt.validation_error("Give 500 mg", "Дать 500 мг", "ru") is None


def test_a_summarised_passage_is_rejected() -> None:
    source = "The patient describes a productive cough. " * 8
    problem = mt.validation_error(source, "Кашель.", "ru")
    assert problem is not None and "suspiciously short" in problem


def test_uzbek_must_use_the_official_apostrophes() -> None:
    assert mt.validation_error("shortness of breath", "nafas qisishi", "uz") is None
    problem = mt.validation_error("cough", "yo'tal", "uz")
    assert problem is not None and "apostrophe" in problem


# --------------------------------------------------------------------------
# Batching and degradation
# --------------------------------------------------------------------------

def test_english_is_returned_untouched() -> None:
    assert mt.translate_batch(["Anything at all"], "en") == ["Anything at all"]


def test_an_unsupported_locale_is_returned_untouched() -> None:
    assert mt.translate_batch(["Anything"], "de") == ["Anything"]


def test_a_rejected_item_keeps_the_english_rather_than_storing_a_bad_value(
    monkeypatch,
) -> None:
    """The whole point: a wrong number never reaches the database.

    Both translators are made to return a mangled dose. The batch must come
    back as the English source, not as the mangled text.
    """
    monkeypatch.setattr(mt, "_gemini_batch", lambda texts, target: ["Дать 50 мг"])
    monkeypatch.setattr(mt, "translate_text", lambda text, target, source="en": "Дать 500 мг")

    assert mt.translate_batch(["Give 5 mg"], "ru") == ["Give 5 mg"]


def test_the_legacy_translator_catches_what_gemini_cannot(monkeypatch) -> None:
    monkeypatch.setattr(mt, "_gemini_batch", lambda texts, target: None)
    monkeypatch.setattr(
        mt, "translate_text", lambda text, target, source="en": "Одышка"
    )
    assert mt.translate_batch(["Shortness of breath"], "ru") == ["Одышка"]


def test_one_bad_item_does_not_spoil_the_rest(monkeypatch) -> None:
    monkeypatch.setattr(
        mt,
        "_gemini_batch",
        lambda texts, target: ["Кашель", "Дать 50 мг", "Одышка"],
    )
    monkeypatch.setattr(mt, "translate_text", lambda text, target, source="en": "")

    out = mt.translate_batch(["Cough", "Give 5 mg", "Shortness of breath"], "ru")
    assert out[0] == "Кашель"
    assert out[1] == "Give 5 mg", "the mangled dose must fall back to English"
    assert out[2] == "Одышка"


def test_the_batch_is_split_but_order_is_preserved(monkeypatch) -> None:
    monkeypatch.setattr(mt, "MAX_BATCH_ITEMS", 2)
    calls: list[int] = []

    def fake(texts, target):
        calls.append(len(texts))
        return [f"[{t}]" for t in texts]

    monkeypatch.setattr(mt, "_gemini_batch", fake)
    out = mt.translate_batch(["a", "b", "c", "d", "e"], "ru")

    assert calls == [2, 2, 1]
    assert out == ["[a]", "[b]", "[c]", "[d]", "[e]"]


def test_a_response_of_the_wrong_length_is_not_trusted() -> None:
    assert mt._parse_array('["one"]', 2) is None
    assert mt._parse_array("not json", 1) is None
    assert mt._parse_array('{"a": 1}', 1) is None
    assert mt._parse_array('["one", 2]', 2) is None


def test_a_fenced_response_is_still_parsed() -> None:
    assert mt._parse_array('```json\n["одышка"]\n```', 1) == ["одышка"]


# --------------------------------------------------------------------------
# Glossary
# --------------------------------------------------------------------------

def test_only_the_terms_present_are_sent() -> None:
    found = glossary.terms_for("uz", "The patient reports shortness of breath.")
    assert found["shortness of breath"] == "nafas qisishi"
    assert "myocardial infarction" not in found


def test_the_glossary_covers_both_targets() -> None:
    missing = [
        term
        for term, rendering in glossary.TERMS.items()
        if not rendering.get("ru", "").strip() or not rendering.get("uz", "").strip()
    ]
    assert not missing, f"incomplete glossary entries: {missing}"


def test_uzbek_glossary_uses_the_official_apostrophes() -> None:
    wrong = [
        term
        for term, rendering in glossary.TERMS.items()
        if any(c in rendering["uz"] for c in "'‘’`")
    ]
    assert not wrong, f"non-standard apostrophe in: {wrong}"


def test_russian_glossary_entries_are_actually_russian() -> None:
    latin_ok = {"sepsis", "asthma"}  # loanwords that stay recognisable
    wrong = [
        term
        for term, rendering in glossary.TERMS.items()
        if term not in latin_ok
        and not any("Ѐ" <= c <= "ӿ" for c in rendering["ru"])
    ]
    assert not wrong, f"ru entries with no Cyrillic: {wrong}"


def test_the_prompt_section_is_empty_when_nothing_matches() -> None:
    assert glossary.prompt_section("ru", "The quick brown fox") == ""
