"""Quiz grading and competency."""
from __future__ import annotations

from typing import Dict, List, Sequence

from app.models.quiz import Choice, Question


def grade(
    questions: Sequence[Question],
    choices_by_question: Dict[int, List[Choice]],
    answers: Dict[int, List[int]],
) -> Dict:
    """Grade a submission.

    `answers` maps question id to the list of chosen choice ids. A question is
    correct only when the selected set matches the correct set exactly, so
    guessing every option on a multi-select scores nothing.
    """
    total_points = 0
    earned_points = 0
    per_question = []

    for question in questions:
        if question.id is None:
            continue
        total_points += question.points

        correct_ids = {
            c.id for c in choices_by_question.get(question.id, []) if c.is_correct and c.id is not None
        }
        given_ids = set(answers.get(question.id, []))
        is_correct = bool(correct_ids) and given_ids == correct_ids
        if is_correct:
            earned_points += question.points

        per_question.append(
            {
                "question_id": question.id,
                "correct": is_correct,
                "correct_choice_ids": sorted(correct_ids),
                "given_choice_ids": sorted(given_ids),
                "explanation": question.explanation,
            }
        )

    score = round((earned_points / total_points) * 100) if total_points else 0
    return {
        "score": score,
        "earned_points": earned_points,
        "total_points": total_points,
        "results": per_question,
    }


def competency_band(score: int) -> str:
    if score >= 90:
        return "advanced"
    if score >= 80:
        return "proficient"
    if score >= 60:
        return "developing"
    return "novice"
