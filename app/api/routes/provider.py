from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.entities import (
    ApprovalStatus,
    AssessmentIssue,
    AssessmentTask,
    Course,
    Exam,
    ProviderProfile,
    ProviderType,
    Question,
    User,
    UserRole,
)

router = APIRouter(prefix="/provider", tags=["provider"])
STANDALONE_ASSESSMENT_CATEGORY = "__standalone_assessment__"


def _clean_string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace("\n", ",").split(",")
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    return [str(x).strip() for x in raw if str(x).strip()]


def _provider_or_404(db: Session, user_id: int) -> ProviderProfile:
    profile = db.scalar(select(ProviderProfile).where(ProviderProfile.user_id == user_id))
    if profile:
        return profile
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Provider profile not found")
    try:
        profile = ProviderProfile(
            user_id=user_id,
            provider_type=ProviderType.INDIVIDUAL,
            display_name=user.full_name or user.email.split("@")[0],
            description="",
            approval_status=ApprovalStatus.PENDING,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Provider profile bootstrap failed: {exc}")


@router.get("/workspace/assessments")
def provider_assessments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PROVIDER, UserRole.ADMIN)),
):
    provider = _provider_or_404(db, current_user.id)
    query = select(Exam, Course).join(Course, Course.id == Exam.course_id)
    if current_user.role != UserRole.ADMIN:
        query = query.where(Course.provider_id == provider.id)
    rows = db.execute(query).all()
    exam_ids = [exam.id for exam, _ in rows]
    question_counts = {
        exam_id: count
        for exam_id, count in db.execute(
            select(Question.exam_id, func.count(Question.id)).group_by(Question.exam_id),
        ).all()
    }
    issued_counts = {
        int(exam_id): int(count)
        for exam_id, count in db.execute(
            select(AssessmentIssue.exam_id, func.count(AssessmentIssue.id)).group_by(AssessmentIssue.exam_id),
        ).all()
    }
    taken_counts = {
        int(exam_id): int(count)
        for exam_id, count in db.execute(
            select(AssessmentIssue.exam_id, func.count(AssessmentIssue.id))
            .where(AssessmentIssue.status.in_(["completed", "manual_review"]))
            .group_by(AssessmentIssue.exam_id),
        ).all()
    }
    task_by_exam = {
        task.assessment_id: task
        for task in db.scalars(select(AssessmentTask).where(AssessmentTask.assessment_id.in_(exam_ids))).all()
    } if exam_ids else {}
    return [
        {
            "exam_id": exam.id,
            "title": exam.title,
            "assessment_type": exam.assessment_type or "mcq",
            "instructions": exam.instructions or "",
            "about": exam.assessment_about or "",
            "tools": _clean_string_list(exam.tools_json or []),
            "topics": _clean_string_list(exam.topics_json or []),
            "course_id": course.id,
            "course_title": "Standalone Assessment",
            "is_standalone": True,
            "status": exam.status,
            "pass_score": exam.pass_score,
            "max_attempts": exam.max_attempts,
            "negative_marking": exam.negative_marking,
            "shuffle_questions": exam.shuffle_questions,
            "shuffle_options": exam.shuffle_options,
            "certificate_enabled": exam.certificate_enabled,
            "timing_mode": exam.timing_mode,
            "duration_minutes": exam.duration_minutes,
            "time_per_question_seconds": exam.time_per_question_seconds,
            "questions_per_attempt": exam.questions_per_attempt,
            "total_marks": exam.total_marks,
            "question_count": int(question_counts.get(exam.id, 0)),
            "issued_count": int(issued_counts.get(exam.id, 0)),
            "taken_count": int(taken_counts.get(exam.id, 0)),
            "task": (
                {
                    "id": task_by_exam[exam.id].id,
                    "type": task_by_exam[exam.id].type,
                    "title": task_by_exam[exam.id].title,
                    "description": task_by_exam[exam.id].description,
                    "instructions": task_by_exam[exam.id].instructions,
                    "marks": task_by_exam[exam.id].marks,
                    "metadata": task_by_exam[exam.id].metadata_json or {},
                    "expected_output": task_by_exam[exam.id].expected_output_json or {},
                    "grading_config": task_by_exam[exam.id].grading_config_json or {},
                }
                if exam.id in task_by_exam else None
            ),
        }
        for exam, course in rows
    ]
