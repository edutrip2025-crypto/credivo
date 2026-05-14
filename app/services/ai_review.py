from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AiJobStatus, AiReviewJob, CourseModule, Exam, Question


@dataclass
class AiReviewResult:
    easy_pct: float
    medium_pct: float
    hard_pct: float
    clarity_score: float
    duplicate_ratio: float
    coverage_ratio: float
    readiness_score: float
    flagged_count: int
    flags: dict
    summary: str


def _difficulty_bucket(question_text: str) -> str:
    length = len(question_text.split())
    if length < 12:
        return "easy"
    if length < 25:
        return "medium"
    return "hard"


def review_exam(db: Session, exam: Exam) -> AiReviewResult:
    questions = list(db.scalars(select(Question).where(Question.exam_id == exam.id)).all())
    modules = list(
        db.scalars(
            select(CourseModule).where(CourseModule.course_id == exam.course_id),
        ).all(),
    )
    if not questions:
        return AiReviewResult(0, 0, 0, 0, 0, 0, 0, 0, {"errors": ["No questions found"]}, "No questions uploaded.")

    difficulties = Counter(_difficulty_bucket(q.question_text) for q in questions)
    easy_pct = difficulties["easy"] / len(questions)
    medium_pct = difficulties["medium"] / len(questions)
    hard_pct = difficulties["hard"] / len(questions)

    normalized = [" ".join(q.question_text.lower().split()) for q in questions]
    duplicate_count = len(normalized) - len(set(normalized))
    duplicate_ratio = duplicate_count / len(questions)

    unclear = [q.id for q in questions if len(q.question_text.split()) < 5 or "??" in q.question_text]
    clarity_score = max(0.0, 100 - (len(unclear) / len(questions)) * 100)

    matched_modules = 0
    for module in modules:
        key = module.title.lower().strip()
        if key and any(key in q.question_text.lower() for q in questions):
            matched_modules += 1
    coverage_ratio = (matched_modules / len(modules)) if modules else 0.0

    readiness_score = (
        (0.35 * clarity_score)
        + (0.25 * ((1 - duplicate_ratio) * 100))
        + (0.20 * (coverage_ratio * 100))
        + (0.20 * ((medium_pct + hard_pct) * 100))
    )
    flagged_count = len(unclear) + duplicate_count
    flags = {
        "unclear_question_ids": unclear,
        "duplicate_count": duplicate_count,
        "module_coverage_matches": matched_modules,
        "module_count": len(modules),
    }

    summary = (
        f"{round(easy_pct * 100)}% easy, {round(medium_pct * 100)}% medium, {round(hard_pct * 100)}% hard. "
        f"{len(unclear)} unclear questions, duplication risk {round(duplicate_ratio * 100)}%. "
        f"Syllabus coverage {round(coverage_ratio * 100)}%."
    )
    return AiReviewResult(
        easy_pct=easy_pct * 100,
        medium_pct=medium_pct * 100,
        hard_pct=hard_pct * 100,
        clarity_score=clarity_score,
        duplicate_ratio=duplicate_ratio,
        coverage_ratio=coverage_ratio * 100,
        readiness_score=readiness_score,
        flagged_count=flagged_count,
        flags=flags,
        summary=summary,
    )


def upsert_ai_review(db: Session, exam: Exam) -> AiReviewJob:
    review_result = review_exam(db, exam)
    review_job = db.scalar(select(AiReviewJob).where(AiReviewJob.exam_id == exam.id))
    if not review_job:
        review_job = AiReviewJob(exam_id=exam.id)
        db.add(review_job)

    review_job.status = AiJobStatus.COMPLETED
    review_job.difficulty_easy_pct = review_result.easy_pct
    review_job.difficulty_medium_pct = review_result.medium_pct
    review_job.difficulty_hard_pct = review_result.hard_pct
    review_job.clarity_score = review_result.clarity_score
    review_job.duplication_risk = review_result.duplicate_ratio
    review_job.syllabus_coverage_estimate = review_result.coverage_ratio
    review_job.certification_readiness_score = review_result.readiness_score
    review_job.flagged_questions_count = review_result.flagged_count
    review_job.flags_json = review_result.flags
    review_job.summary = review_result.summary
    db.flush()
    return review_job
