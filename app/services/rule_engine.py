from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import AiReviewJob, Exam, ExamRule, Question


@dataclass
class RuleCheckResult:
    approved: bool
    reasons: list[str]


def evaluate_exam_rules(db: Session, exam: Exam) -> RuleCheckResult:
    settings = get_settings()
    rule = db.scalar(select(ExamRule).where(ExamRule.exam_id == exam.id))
    if not rule:
        rule = ExamRule(exam_id=exam.id)
        db.add(rule)
        db.flush()

    questions = list(db.scalars(select(Question).where(Question.exam_id == exam.id)).all())
    review = db.scalar(select(AiReviewJob).where(AiReviewJob.exam_id == exam.id))
    reasons: list[str] = []

    if len(questions) < rule.min_questions:
        reasons.append(f"Minimum {rule.min_questions} questions required.")

    if exam.pass_score < rule.min_pass_score:
        reasons.append(f"Pass score must be at least {rule.min_pass_score}%.")

    if settings.enable_ai_review and review:
        easy_ratio = review.difficulty_easy_pct / 100
        if easy_ratio > rule.max_easy_ratio:
            reasons.append("Too many easy questions.")
        if review.duplication_risk > rule.max_duplicate_ratio:
            reasons.append("Duplicate-like questions exceed allowed threshold.")
        module_matches = int(review.flags_json.get("module_coverage_matches", 0)) if review.flags_json else 0
        if module_matches < rule.min_syllabus_areas:
            reasons.append("Insufficient syllabus coverage.")
        ambiguous_ratio = (review.flagged_questions_count / max(len(questions), 1))
        if ambiguous_ratio > rule.max_ambiguous_ratio:
            reasons.append("Ambiguous/flagged questions exceed threshold.")
    elif settings.enable_ai_review:
        # Do not hard-block publishing when AI review is unavailable.
        # AI signals are applied when review data exists.
        pass

    return RuleCheckResult(approved=len(reasons) == 0, reasons=reasons)
