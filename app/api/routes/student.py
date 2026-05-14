from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.entities import (
    AssessmentIssue,
    AttemptEvent,
    AttemptStatus,
    Exam,
    ExamAttempt,
    ExamStatus,
    Option,
    ProctorSession,
    ProctorTrainingFeedback,
    Question,
    Result,
    StudentAnswer,
    User,
    UserRole,
)
from app.schemas import AnswerSaveRequest, EventRequest, ProctorTrainingFeedbackCreate, ResultOut
from app.services.proctoring_ai import evaluate_proctor_session
from app.services.scoring import score_attempt

router = APIRouter(prefix="/student", tags=["student"])
_attempt_start_lock = Lock()
_attempt_submit_lock = Lock()


def _attempt_or_404(db: Session, attempt_id: int, student_id: int) -> ExamAttempt:
    attempt = db.get(ExamAttempt, attempt_id)
    if not attempt or attempt.student_id != student_id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


def _result_payload(db: Session, result: Result, attempt: ExamAttempt) -> dict:
    feedback_count = int(db.scalar(select(func.count(ProctorTrainingFeedback.id)).where(ProctorTrainingFeedback.attempt_id == attempt.id)) or 0)
    return {
        "id": result.id,
        "attempt_id": result.attempt_id,
        "student_id": result.student_id,
        "exam_id": result.exam_id,
        "score": result.score,
        "percentage": result.percentage,
        "passed": result.passed,
        "correct_count": None,
        "wrong_count": None,
        "total_questions": None,
        "training_feedback_count": feedback_count,
    }


@router.get("/assessments/catalog")
def assessment_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    exams = db.scalars(select(Exam).where(Exam.status == ExamStatus.PUBLISHED).order_by(Exam.created_at.desc())).all()
    question_counts = {
        exam_id: count
        for exam_id, count in db.execute(select(Question.exam_id, func.count(Question.id)).group_by(Question.exam_id)).all()
    }
    return [
        {
            "exam_id": exam.id,
            "title": exam.title,
            "assessment_type": exam.assessment_type or "mcq",
            "instructions": exam.instructions or "",
            "about": exam.assessment_about or "",
            "tools": exam.tools_json or [],
            "topics": exam.topics_json or [],
            "duration_minutes": exam.duration_minutes,
            "timing_mode": exam.timing_mode,
            "time_per_question_seconds": exam.time_per_question_seconds,
            "questions_per_attempt": exam.questions_per_attempt,
            "pass_score": exam.pass_score,
            "question_count": int(question_counts.get(exam.id, 0)),
        }
        for exam in exams
    ]


@router.post("/exams/{exam_id}/attempts/start", status_code=status.HTTP_201_CREATED)
def start_attempt(
    exam_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    with _attempt_start_lock:
        exam = db.get(Exam, exam_id)
        if not exam or exam.status != ExamStatus.PUBLISHED:
            raise HTTPException(status_code=404, detail="Assessment not available")
        existing_count = int(db.scalar(select(func.count(ExamAttempt.id)).where(and_(ExamAttempt.exam_id == exam_id, ExamAttempt.student_id == current_user.id))) or 0)
        if exam.max_attempts and existing_count >= int(exam.max_attempts):
            raise HTTPException(status_code=403, detail="Maximum attempts reached")
        questions = list(db.scalars(select(Question.id).where(Question.exam_id == exam_id)).all())
        assigned = questions[: int(exam.questions_per_attempt or 0)] if int(exam.questions_per_attempt or 0) > 0 else questions
        attempt = ExamAttempt(
            exam_id=exam_id,
            student_id=current_user.id,
            attempt_number=existing_count + 1,
            status=AttemptStatus.IN_PROGRESS,
            assigned_question_ids=list(assigned),
        )
        db.add(attempt)
        issue = db.scalar(select(AssessmentIssue).where(and_(AssessmentIssue.exam_id == exam_id, AssessmentIssue.candidate_user_id == current_user.id)).order_by(AssessmentIssue.issued_at.desc()))
        if issue and issue.status == "issued":
            issue.status = "started"
            issue.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(attempt)
        return {"attempt_id": attempt.id, "exam_id": exam_id, "attempt_number": attempt.attempt_number}


@router.get("/attempts/{attempt_id}/paper")
def attempt_paper(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    attempt = _attempt_or_404(db, attempt_id, current_user.id)
    exam = db.get(Exam, attempt.exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")
    query = select(Question).where(Question.exam_id == exam.id)
    if attempt.assigned_question_ids:
        query = query.where(Question.id.in_(attempt.assigned_question_ids))
    questions = db.scalars(query).all()
    return {
        "attempt_id": attempt.id,
        "exam": {
            "id": exam.id,
            "title": exam.title,
            "instructions": exam.instructions,
            "duration_minutes": exam.duration_minutes,
            "timing_mode": exam.timing_mode,
            "time_per_question_seconds": exam.time_per_question_seconds,
        },
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "marks": q.marks,
                "options": [
                    {"id": opt.id, "option_text": opt.option_text, "position": opt.position}
                    for opt in db.scalars(select(Option).where(Option.question_id == q.id).order_by(Option.position.asc())).all()
                ],
            }
            for q in questions
        ],
    }


@router.post("/attempts/{attempt_id}/answers")
def save_answer(
    attempt_id: int,
    payload: AnswerSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    attempt = _attempt_or_404(db, attempt_id, current_user.id)
    if attempt.status != AttemptStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail="Attempt is not active")
    answer = db.scalar(select(StudentAnswer).where(and_(StudentAnswer.attempt_id == attempt_id, StudentAnswer.question_id == payload.question_id)))
    if not answer:
        answer = StudentAnswer(attempt_id=attempt_id, question_id=payload.question_id)
        db.add(answer)
    answer.selected_option_ids = payload.selected_option_ids or []
    answer.text_answer = payload.text_answer
    db.commit()
    return {"saved": True}


@router.post("/attempts/{attempt_id}/events")
def log_attempt_event(
    attempt_id: int,
    payload: EventRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    _attempt_or_404(db, attempt_id, current_user.id)
    db.add(AttemptEvent(attempt_id=attempt_id, event_type=payload.event_type, payload_json=payload.payload or {}))
    db.commit()
    return {"logged": True}


@router.post("/attempts/{attempt_id}/submit", response_model=ResultOut)
def submit_attempt(
    attempt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    with _attempt_submit_lock:
        attempt = _attempt_or_404(db, attempt_id, current_user.id)
        exam = db.get(Exam, attempt.exam_id)
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found")
        score, percentage, _correct, _wrong, _total = score_attempt(db, attempt.id, exam.id, exam.negative_marking, attempt.assigned_question_ids)
        proctor_session = db.scalar(select(ProctorSession).where(ProctorSession.attempt_id == attempt.id).order_by(ProctorSession.started_at.desc()))
        if proctor_session:
            decision = evaluate_proctor_session(db, proctor_session.id)
            if decision.get("hard_fail"):
                percentage = 0
                score = 0
        passed = percentage >= float(exam.pass_score or 0)
        attempt.status = AttemptStatus.SUBMITTED
        attempt.submitted_at = datetime.now(timezone.utc)
        attempt.score = score
        attempt.percentage = percentage
        attempt.passed = passed
        result = db.scalar(select(Result).where(Result.attempt_id == attempt.id))
        if not result:
            result = Result(attempt_id=attempt.id, student_id=current_user.id, exam_id=exam.id, score=score, percentage=percentage, passed=passed)
            db.add(result)
        else:
            result.score = score
            result.percentage = percentage
            result.passed = passed
        issue = db.scalar(select(AssessmentIssue).where(and_(AssessmentIssue.exam_id == exam.id, AssessmentIssue.candidate_user_id == current_user.id)).order_by(AssessmentIssue.issued_at.desc()))
        if issue:
            issue.status = "completed"
            issue.completed_at = datetime.now(timezone.utc)
            issue.score_pct = percentage
            issue.passed = passed
            issue.result_json = {"attempt_id": attempt.id, "score": score, "percentage": percentage, "passed": passed}
        db.commit()
        db.refresh(result)
        return _result_payload(db, result, attempt)


@router.get("/attempts/{attempt_id}/result", response_model=ResultOut)
def get_result(
    attempt_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    attempt = _attempt_or_404(db, attempt_id, current_user.id)
    result = db.scalar(select(Result).where(Result.attempt_id == attempt.id))
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return _result_payload(db, result, attempt)


@router.post("/attempts/{attempt_id}/proctor-training-feedback")
def save_proctor_training_feedback(
    attempt_id: int,
    payload: ProctorTrainingFeedbackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT)),
):
    attempt = _attempt_or_404(db, attempt_id, current_user.id)
    result = db.scalar(select(Result).where(Result.attempt_id == attempt.id))
    session = db.scalar(select(ProctorSession).where(ProctorSession.attempt_id == attempt.id).order_by(ProctorSession.started_at.desc()))
    item = ProctorTrainingFeedback(
        attempt_id=attempt.id,
        result_id=result.id if result else None,
        session_id=session.id if session else None,
        actor_user_id=current_user.id,
        feedback_label=payload.training_result,
        comment=payload.comment,
        final_result_passed=result.passed if result else None,
    )
    db.add(item)
    db.commit()
    return {"saved": True, "feedback_id": item.id}
