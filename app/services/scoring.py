from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Option, Question, QuestionType, StudentAnswer


def score_attempt(
    db: Session,
    attempt_id: int,
    exam_id: int,
    negative_marking: bool,
    assigned_question_ids: list[int] | None = None,
) -> tuple[float, float, int, int, int]:
    query = select(Question).where(Question.exam_id == exam_id)
    if assigned_question_ids:
        query = query.where(Question.id.in_(assigned_question_ids))
    questions = list(db.scalars(query).all())
    answers = list(db.scalars(select(StudentAnswer).where(StudentAnswer.attempt_id == attempt_id)).all())
    answer_map = {a.question_id: a for a in answers}

    total_possible = sum(q.marks for q in questions)
    score = 0.0
    correct_count = 0
    wrong_count = 0

    for question in questions:
        answer = answer_map.get(question.id)
        if not answer:
            wrong_count += 1
            continue

        if question.question_type in [QuestionType.MCQ_SINGLE, QuestionType.MCQ_MULTI]:
            correct_ids = set(
                db.scalars(
                    select(Option.id).where(Option.question_id == question.id, Option.is_correct.is_(True)),
                ).all(),
            )
            selected = set(answer.selected_option_ids or [])
            if selected == correct_ids:
                answer.is_correct = True
                answer.awarded_marks = question.marks
                score += question.marks
                correct_count += 1
            else:
                answer.is_correct = False
                wrong_count += 1
                if negative_marking:
                    answer.awarded_marks = -abs(question.negative_marks)
                    score -= abs(question.negative_marks)
                else:
                    answer.awarded_marks = 0
        else:
            answer.is_correct = None
            answer.awarded_marks = 0

    percentage = (score / total_possible * 100) if total_possible > 0 else 0
    return score, percentage, correct_count, wrong_count, len(questions)
