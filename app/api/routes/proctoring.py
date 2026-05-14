from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import (
    AttemptStatus,
    AuditLog,
    ExamAttempt,
    ProctorEvidence,
    ProctorEvent,
    ProctorSession,
    ProctorDatasetSource,
    ProctorModelRun,
    ProctorTrainingFeedback,
    User,
    UserRole,
)
from app.schemas import (
    ProctorDatasetSourceCreate,
    ProctorDatasetSourceUpdate,
    ProctorEventCreate,
    ProctorFinalizeRequest,
    ProctorHardNegativeIngestRequest,
    ProctorModelTrainRequest,
    ProctorReviewRequest,
    ProctorSessionStartRequest,
    ProctorTrainingFeedbackCreate,
)
from app.services.proctor_hard_negative import (
    ingest_hard_negative_sessions_from_feedback,
    summarize_curated_hard_negatives,
)
from app.services.proctor_retention import run_proctor_retention_cleanup
from app.services.proctor_training import TrainConfig, train_proctor_model_from_feedback
from app.services.proctoring_ai import evaluate_proctor_session, get_proctor_model_status, reset_proctor_model_cache
from app.services.media_storage import resolve_media_url, upload_file_to_cloud_storage

router = APIRouter(prefix="/proctoring", tags=["proctoring"])
_session_start_lock = Lock()


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def _session_or_404(db: Session, session_id: int) -> ProctorSession:
    item = db.get(ProctorSession, session_id)
    if not item:
        raise HTTPException(status_code=404, detail="Proctor session not found")
    return item


def _can_access_session(user: User, item: ProctorSession) -> bool:
    return _is_admin(user) or item.actor_user_id == user.id


def _assert_session_access(user: User, item: ProctorSession) -> None:
    if not _can_access_session(user, item):
        raise HTTPException(status_code=403, detail="Access denied")


def _preview_feedback_filter(session_id: int):
    return and_(
        ProctorTrainingFeedback.session_id == session_id,
        ProctorTrainingFeedback.attempt_id.is_(None),
    )


def _latest_preview_training_feedback(db: Session, session_id: int) -> tuple[ProctorTrainingFeedback | None, int]:
    count = int(
        db.scalar(select(func.count(ProctorTrainingFeedback.id)).where(_preview_feedback_filter(session_id))) or 0,
    )
    latest = db.scalar(
        select(ProctorTrainingFeedback)
        .where(_preview_feedback_filter(session_id))
        .order_by(ProctorTrainingFeedback.created_at.desc(), ProctorTrainingFeedback.id.desc()),
    )
    return latest, count


def _risk_weight(severity: str) -> tuple[float, int]:
    s = (severity or "info").lower().strip()
    if s == "critical":
        return 15.0, 1
    if s == "warning":
        return 5.0, 1
    return 0.5, 0


def _recompute_flag(item: ProctorSession) -> None:
    item.is_flagged = bool(item.warning_count >= 5 or item.risk_score >= 20)


def _active_session_for_user(db: Session, user_id: int) -> ProctorSession | None:
    return db.scalar(
        select(ProctorSession)
        .where(and_(ProctorSession.actor_user_id == user_id, ProctorSession.status == "active"))
        .order_by(ProctorSession.started_at.desc(), ProctorSession.id.desc()),
    )


def _media_root() -> Path:
    root = Path(get_settings().resolved_media_dir) / "proctoring"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_audit(
    db: Session,
    *,
    actor_user_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details_json=details or {},
        ),
    )


@router.get("/model/status")
def proctor_model_status(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return get_proctor_model_status()


@router.get("/admin/dataset-sources")
def admin_list_dataset_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    rows = list(
        db.scalars(
            select(ProctorDatasetSource).order_by(ProctorDatasetSource.created_at.desc(), ProctorDatasetSource.id.desc()),
        ).all(),
    )
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "source_type": r.source_type,
                "source_path": r.source_path,
                "is_enabled": r.is_enabled,
                "notes": r.notes,
                "created_by_user_id": r.created_by_user_id,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/admin/dataset-sources", status_code=status.HTTP_201_CREATED)
def admin_create_dataset_source(
    payload: ProctorDatasetSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Dataset source name is required")
    exists = db.scalar(select(ProctorDatasetSource).where(ProctorDatasetSource.name == name))
    if exists:
        raise HTTPException(status_code=409, detail="Dataset source name already exists")
    source_type = str(payload.source_type or "local_csv").strip().lower()
    if source_type not in {"local_csv", "local_dir", "s3_prefix"}:
        raise HTTPException(status_code=400, detail="source_type must be local_csv, local_dir, or s3_prefix")
    item = ProctorDatasetSource(
        name=name,
        source_type=source_type,
        source_path=str(payload.source_path or "").strip(),
        is_enabled=bool(payload.is_enabled),
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "name": item.name,
        "source_type": item.source_type,
        "source_path": item.source_path,
        "is_enabled": item.is_enabled,
        "notes": item.notes,
        "created_by_user_id": item.created_by_user_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.patch("/admin/dataset-sources/{source_id}")
def admin_update_dataset_source(
    source_id: int,
    payload: ProctorDatasetSourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    item = db.get(ProctorDatasetSource, source_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset source not found")
    data = payload.model_dump(exclude_unset=True)
    if "source_type" in data:
        source_type = str(data["source_type"] or "").strip().lower()
        if source_type not in {"local_csv", "local_dir", "s3_prefix"}:
            raise HTTPException(status_code=400, detail="source_type must be local_csv, local_dir, or s3_prefix")
        item.source_type = source_type
    if "source_path" in data:
        item.source_path = str(data["source_path"] or "").strip()
    if "is_enabled" in data:
        item.is_enabled = bool(data["is_enabled"])
    if "notes" in data:
        item.notes = (str(data["notes"] or "").strip() or None)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "name": item.name,
        "source_type": item.source_type,
        "source_path": item.source_path,
        "is_enabled": item.is_enabled,
        "notes": item.notes,
        "created_by_user_id": item.created_by_user_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/admin/model-runs")
def admin_model_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    limit = min(max(limit, 1), 100)
    rows = list(
        db.scalars(
            select(ProctorModelRun)
            .order_by(ProctorModelRun.created_at.desc(), ProctorModelRun.id.desc())
            .limit(limit),
        ).all(),
    )
    return {
        "items": [
            {
                "id": r.id,
                "model_key": r.model_key,
                "feature_space": r.feature_space,
                "status": r.status,
                "sample_count": r.sample_count,
                "validation_count": r.validation_count,
                "precision": r.precision,
                "recall": r.recall,
                "f1_score": r.f1_score,
                "roc_auc": r.roc_auc,
                "warning_threshold": r.warning_threshold,
                "manual_review_threshold": r.manual_review_threshold,
                "critical_threshold": r.critical_threshold,
                "summary": r.summary_json,
                "error_message": r.error_message,
                "created_by_user_id": r.created_by_user_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/admin/train-model")
def admin_train_proctor_model(
    payload: ProctorModelTrainRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    run = ProctorModelRun(
        model_key="logistic",
        feature_space="event_risk_v1",
        status="running",
        created_by_user_id=current_user.id,
        summary_json={
            "minimum_samples": payload.minimum_samples,
            "validation_split": payload.validation_split,
            "target_recall": payload.target_recall,
            "max_false_positive_rate": payload.max_false_positive_rate,
            "strict_mode": payload.strict_mode,
            "class_balance_strength": payload.class_balance_strength,
            "hard_negative_weight": payload.hard_negative_weight,
            "hard_positive_weight": payload.hard_positive_weight,
            "hard_example_min_prob": payload.hard_example_min_prob,
            "curated_hard_negative_weight": payload.curated_hard_negative_weight,
            "max_curated_hard_negatives": payload.max_curated_hard_negatives,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        result = train_proctor_model_from_feedback(
            db,
            TrainConfig(
                minimum_samples=payload.minimum_samples,
                validation_split=payload.validation_split,
                target_recall=payload.target_recall,
                max_false_positive_rate=payload.max_false_positive_rate,
                strict_mode=payload.strict_mode,
                class_balance_strength=payload.class_balance_strength,
                hard_negative_weight=payload.hard_negative_weight,
                hard_positive_weight=payload.hard_positive_weight,
                hard_example_min_prob=payload.hard_example_min_prob,
                curated_hard_negative_weight=payload.curated_hard_negative_weight,
                max_curated_hard_negatives=payload.max_curated_hard_negatives,
            ),
        )
        run.status = "completed"
        run.sample_count = int(result.get("sample_count") or 0)
        run.validation_count = int(result.get("validation_count") or 0)
        run.precision = float(result.get("precision")) if result.get("precision") is not None else None
        run.recall = float(result.get("recall")) if result.get("recall") is not None else None
        run.f1_score = float(result.get("f1_score")) if result.get("f1_score") is not None else None
        run.roc_auc = float(result.get("roc_auc")) if result.get("roc_auc") is not None else None
        run.warning_threshold = float(result.get("warning_threshold")) if result.get("warning_threshold") is not None else None
        run.manual_review_threshold = (
            float(result.get("manual_review_threshold"))
            if result.get("manual_review_threshold") is not None
            else None
        )
        run.critical_threshold = float(result.get("critical_threshold")) if result.get("critical_threshold") is not None else None
        run.summary_json = result.get("summary") or {}
        run.error_message = None
        db.commit()
        reset_proctor_model_cache()
        return {"status": "ok", "run_id": run.id, **result}
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Model training failed: {exc}") from exc


@router.get("/admin/hard-negatives/summary")
def admin_hard_negative_summary(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return summarize_curated_hard_negatives()


@router.post("/admin/hard-negatives/ingest")
def admin_ingest_hard_negatives(
    payload: ProctorHardNegativeIngestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    out = ingest_hard_negative_sessions_from_feedback(
        db,
        lookback_days=payload.lookback_days,
        limit=payload.limit,
        min_model_probability=payload.min_model_probability,
        include_preview_sessions=payload.include_preview_sessions,
    )
    return out


@router.post("/admin/model/reload")
def admin_reload_proctor_model(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    reset_proctor_model_cache()
    return {"status": "ok", "message": "Proctor model cache reloaded"}


@router.get("/admin/sessions/{session_id}/evaluation")
def admin_session_evaluation(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    item = _session_or_404(db, session_id)
    ai_eval = evaluate_proctor_session(db, item)
    events_count = db.scalar(select(func.count(ProctorEvent.id)).where(ProctorEvent.session_id == item.id)) or 0
    evidence_count = db.scalar(select(func.count(ProctorEvidence.id)).where(ProctorEvidence.session_id == item.id)) or 0
    events = list(
        db.scalars(
            select(ProctorEvent)
            .where(ProctorEvent.session_id == item.id)
            .order_by(ProctorEvent.created_at.desc()),
        ).all(),
    )
    event_type_counts: dict[str, int] = {}
    recent_events: list[dict[str, object]] = []
    training_feedback: list[dict[str, object]] = []
    training_feedback_count = 0
    timeline: list[dict[str, object]] = []
    total_seconds = max(
        1.0,
        float(((item.ended_at or datetime.now(timezone.utc)) - item.started_at).total_seconds() if item.started_at else 1.0),
    )
    bucket_count = 12
    bucket_size = total_seconds / bucket_count
    timeline = [
        {"index": idx, "critical": 0, "warning": 0, "info": 0, "score": 0.0}
        for idx in range(bucket_count)
    ]
    for event in events:
        key = str(event.event_type or "unknown")
        event_type_counts[key] = event_type_counts.get(key, 0) + 1
        if len(recent_events) < 8:
            recent_events.append(
                {
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "confidence": event.confidence,
                    "created_at": event.created_at,
                    "details": event.details_json,
                },
            )
        if item.started_at and event.created_at:
            elapsed = max(0.0, float((event.created_at - item.started_at).total_seconds()))
            bucket_idx = min(bucket_count - 1, int(elapsed / max(bucket_size, 0.001)))
            bucket = timeline[bucket_idx]
            sev = str(event.severity or "info").lower()
            if sev == "critical":
                bucket["critical"] = int(bucket["critical"]) + 1
                bucket["score"] = float(bucket["score"]) + 1.0
            elif sev == "warning":
                bucket["warning"] = int(bucket["warning"]) + 1
                bucket["score"] = float(bucket["score"]) + 0.6
            else:
                bucket["info"] = int(bucket["info"]) + 1
                bucket["score"] = float(bucket["score"]) + 0.2
    feedback_rows: list[ProctorTrainingFeedback] = []
    if item.attempt_id:
        feedback_rows = list(
            db.scalars(
                select(ProctorTrainingFeedback)
                .where(ProctorTrainingFeedback.attempt_id == item.attempt_id)
                .order_by(ProctorTrainingFeedback.created_at.desc(), ProctorTrainingFeedback.id.desc()),
            ).all(),
        )
    elif str(item.mode or "").lower() == "preview":
        feedback_rows = list(
            db.scalars(
                select(ProctorTrainingFeedback)
                .where(_preview_feedback_filter(item.id))
                .order_by(ProctorTrainingFeedback.created_at.desc(), ProctorTrainingFeedback.id.desc()),
            ).all(),
        )
    training_feedback_count = len(feedback_rows)
    training_feedback = [
        {
            "id": row.id,
            "feedback_label": row.feedback_label,
            "comment": row.comment,
            "model_decision": row.model_decision,
            "model_probability": row.model_probability,
            "final_result_passed": row.final_result_passed,
            "created_at": row.created_at,
        }
        for row in feedback_rows[:8]
    ]
    return {
        "session": {
            "id": item.id,
            "session_code": item.session_code,
            "mode": item.mode,
            "status": item.status,
            "actor_user_id": item.actor_user_id,
            "exam_id": item.exam_id,
            "attempt_id": item.attempt_id,
            "warning_count": item.warning_count,
            "risk_score": item.risk_score,
            "is_flagged": item.is_flagged,
            "admin_review_status": item.admin_review_status,
            "started_at": item.started_at,
            "ended_at": item.ended_at,
        },
        "counts": {
            "events": int(events_count),
            "evidence": int(evidence_count),
        },
        "event_type_counts": event_type_counts,
        "recent_events": recent_events,
        "training_feedback": training_feedback,
        "training_feedback_count": training_feedback_count,
        "timeline": timeline,
        "ai_evaluation": ai_eval,
    }


@router.post("/sessions/start", status_code=status.HTTP_201_CREATED)
def start_session(
    payload: ProctorSessionStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    mode = (payload.mode or "attempt").lower().strip()
    if mode not in {"attempt", "preview"}:
        raise HTTPException(status_code=400, detail="mode must be attempt or preview")
    if mode == "attempt" and not payload.attempt_id:
        raise HTTPException(status_code=400, detail="attempt_id is required for attempt mode")
    if mode == "attempt" and not (payload.consent_camera and payload.consent_microphone and payload.consent_recording):
        raise HTTPException(status_code=400, detail="Proctoring consent for camera, microphone, and recording is required.")

    if payload.attempt_id:
        attempt = db.get(ExamAttempt, payload.attempt_id)
        if not attempt:
            raise HTTPException(status_code=404, detail="Attempt not found")
        if not _is_admin(current_user) and attempt.student_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise HTTPException(status_code=400, detail="Attempt is not in progress")
        exam_id = attempt.exam_id
    else:
        exam_id = payload.exam_id

    with _session_start_lock:
        existing_active = _active_session_for_user(db, current_user.id)
        if existing_active:
            same_target = (
                str(existing_active.mode or "").lower() == mode
                and existing_active.exam_id == exam_id
                and existing_active.attempt_id == payload.attempt_id
            )
            if same_target:
                return {
                    "session_id": existing_active.id,
                    "session_code": existing_active.session_code,
                    "mode": existing_active.mode,
                    "status": existing_active.status,
                    "exam_id": existing_active.exam_id,
                    "attempt_id": existing_active.attempt_id,
                }
            raise HTTPException(
                status_code=409,
                detail="Another test session is already active for this user. Close or submit that session before starting a new one.",
            )

        item = ProctorSession(
            session_code=uuid4().hex,
            mode=mode,
            status="active",
            actor_user_id=current_user.id,
            exam_id=exam_id,
            attempt_id=payload.attempt_id,
            warning_count=0,
            risk_score=0,
            is_flagged=False,
            admin_review_status="pending",
        )
        db.add(item)
        db.flush()
        db.add(
            ProctorEvent(
                session_id=item.id,
                event_type="consent_attested",
                severity="info",
                confidence=None,
                details_json={
                    "camera": bool(payload.consent_camera),
                    "microphone": bool(payload.consent_microphone),
                    "recording": bool(payload.consent_recording),
                },
            ),
        )
        _write_audit(
            db,
            actor_user_id=current_user.id,
            action="proctor_session_start",
            target_type="proctor_session",
            target_id=item.id,
            details={"mode": mode, "exam_id": exam_id, "attempt_id": payload.attempt_id},
        )
        db.commit()
        db.refresh(item)
    return {
        "session_id": item.id,
        "session_code": item.session_code,
        "mode": item.mode,
        "status": item.status,
        "exam_id": item.exam_id,
        "attempt_id": item.attempt_id,
    }


@router.post("/admin/retention/cleanup")
def admin_run_retention_cleanup(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = run_proctor_retention_cleanup(db, days=days)
    _write_audit(
        db,
        actor_user_id=current_user.id,
        action="proctor_retention_cleanup",
        target_type="proctor_session",
        target_id=None,
        details={
            "days": result.days,
            "cutoff": result.cutoff_iso,
            "sessions_deleted": result.sessions_deleted,
            "evidence_rows_deleted": result.evidence_rows_deleted,
            "local_files_deleted": result.local_files_deleted,
        },
    )
    db.commit()
    return {
        "status": "ok",
        "cutoff": result.cutoff_iso,
        "days": result.days,
        "sessions_deleted": result.sessions_deleted,
        "evidence_rows_deleted": result.evidence_rows_deleted,
        "local_files_deleted": result.local_files_deleted,
    }


@router.post("/sessions/{session_id}/events", status_code=status.HTTP_201_CREATED)
def add_event(
    session_id: int,
    payload: ProctorEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    item = _session_or_404(db, session_id)
    _assert_session_access(current_user, item)
    if item.status != "active":
        raise HTTPException(status_code=400, detail="Session is not active")

    weight, warn_inc = _risk_weight(payload.severity)
    item.risk_score += weight
    item.warning_count += warn_inc
    _recompute_flag(item)

    event = ProctorEvent(
        session_id=item.id,
        event_type=payload.event_type,
        severity=payload.severity,
        confidence=payload.confidence,
        details_json=payload.details or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "event_id": event.id,
        "session_id": item.id,
        "warning_count": item.warning_count,
        "risk_score": item.risk_score,
        "is_flagged": item.is_flagged,
    }


@router.post("/sessions/{session_id}/evidence", status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    session_id: int,
    file: UploadFile = File(...),
    evidence_type: str = Form(default="image"),
    event_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    item = _session_or_404(db, session_id)
    _assert_session_access(current_user, item)
    if item.status != "active":
        raise HTTPException(status_code=400, detail="Session is not active")

    if event_id:
        event = db.get(ProctorEvent, event_id)
        if not event or event.session_id != item.id:
            raise HTTPException(status_code=404, detail="Linked event not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    root = _media_root() / item.session_code
    root.mkdir(parents=True, exist_ok=True)
    safe_ext = Path(file.filename or "evidence.bin").suffix or ".bin"
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex}{safe_ext}"
    out_path = root / filename
    out_path.write_bytes(raw)
    settings = get_settings()
    if settings.resolved_object_storage_backend == "local":
        rel = out_path.relative_to(Path(settings.resolved_media_dir)).as_posix()
        url = f"/media/{rel}"
    else:
        try:
            url = upload_file_to_cloud_storage(
                out_path,
                object_path=f"proctoring/{item.session_code}/{filename}",
                content_type=file.content_type or "application/octet-stream",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to upload proctor evidence: {exc}") from exc

    ev = ProctorEvidence(
        session_id=item.id,
        event_id=event_id,
        evidence_type=evidence_type,
        file_url=url,
        mime_type=file.content_type,
        size_bytes=len(raw),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return {"evidence_id": ev.id, "file_url": resolve_media_url(ev.file_url), "storage_ref": ev.file_url, "size_bytes": ev.size_bytes}


@router.post("/sessions/{session_id}/finalize")
def finalize_session(
    session_id: int,
    payload: ProctorFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    item = _session_or_404(db, session_id)
    _assert_session_access(current_user, item)
    item.status = "completed"
    item.ended_reason = payload.ended_reason or "completed"
    item.ended_at = datetime.now(timezone.utc)
    ai_eval = evaluate_proctor_session(db, item)
    item.risk_score = max(float(item.risk_score or 0), float(ai_eval.get("final_probability", 0)) * 100.0)
    item.is_flagged = bool(ai_eval.get("is_flagged", False) or item.is_flagged)
    _recompute_flag(item)
    _write_audit(
        db,
        actor_user_id=current_user.id,
        action="proctor_session_finalize",
        target_type="proctor_session",
        target_id=item.id,
        details={"ended_reason": item.ended_reason, "risk_score": item.risk_score, "is_flagged": item.is_flagged},
    )
    db.commit()
    return {
        "session_id": item.id,
        "status": item.status,
        "warning_count": item.warning_count,
        "risk_score": item.risk_score,
        "is_flagged": item.is_flagged,
        "ai_evaluation": ai_eval,
    }


@router.get("/sessions/{session_id}/training-feedback/latest")
def latest_preview_training_feedback(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    item = _session_or_404(db, session_id)
    _assert_session_access(current_user, item)
    if str(item.mode or "").lower() != "preview":
        raise HTTPException(status_code=400, detail="Training labels for this flow are only stored on preview sessions")
    latest, count = _latest_preview_training_feedback(db, item.id)
    return {
        "training_feedback_status": latest.feedback_label if latest else None,
        "training_feedback_comment": latest.comment if latest else None,
        "training_feedback_count": count,
    }


@router.post("/sessions/{session_id}/training-feedback")
def save_preview_training_feedback(
    session_id: int,
    payload: ProctorTrainingFeedbackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    item = _session_or_404(db, session_id)
    _assert_session_access(current_user, item)
    if str(item.mode or "").lower() != "preview" or item.attempt_id is not None:
        raise HTTPException(status_code=400, detail="Only preview proctor sessions accept this training feedback endpoint")
    if item.status != "completed":
        raise HTTPException(status_code=400, detail="Finish the assessment session before saving training review")

    feedback_label = str(payload.training_result or "correct").strip().lower()
    if feedback_label not in {"correct", "incorrect"}:
        raise HTTPException(status_code=400, detail="training_result must be correct or incorrect")

    proctor_eval = evaluate_proctor_session(db, item)
    item_row = ProctorTrainingFeedback(
        attempt_id=None,
        result_id=None,
        session_id=item.id,
        actor_user_id=current_user.id,
        feedback_label=feedback_label,
        comment=(payload.comment or "").strip() or None,
        model_decision=(proctor_eval or {}).get("decision"),
        model_probability=(proctor_eval or {}).get("final_probability"),
        final_result_passed=None,
    )
    db.add(item_row)
    db.commit()
    db.refresh(item_row)
    _, feedback_count = _latest_preview_training_feedback(db, item.id)
    return {
        "id": item_row.id,
        "session_id": item_row.session_id,
        "training_feedback_status": item_row.feedback_label,
        "training_feedback_comment": item_row.comment,
        "training_feedback_count": feedback_count,
        "created_at": item_row.created_at,
    }


@router.get("/sessions/{session_id}")
def session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STUDENT, UserRole.PROVIDER, UserRole.ADMIN, allow_unapproved=True)),
):
    item = _session_or_404(db, session_id)
    _assert_session_access(current_user, item)
    events = list(
        db.scalars(select(ProctorEvent).where(ProctorEvent.session_id == item.id).order_by(ProctorEvent.created_at.desc())).all(),
    )
    evidence = list(
        db.scalars(select(ProctorEvidence).where(ProctorEvidence.session_id == item.id).order_by(ProctorEvidence.created_at.desc())).all(),
    )
    ai_eval = evaluate_proctor_session(db, item) if item.status == "completed" else None
    return {
        "session": {
            "id": item.id,
            "session_code": item.session_code,
            "mode": item.mode,
            "status": item.status,
            "actor_user_id": item.actor_user_id,
            "exam_id": item.exam_id,
            "attempt_id": item.attempt_id,
            "warning_count": item.warning_count,
            "risk_score": item.risk_score,
            "is_flagged": item.is_flagged,
            "admin_review_status": item.admin_review_status,
            "admin_notes": item.admin_notes,
            "started_at": item.started_at,
            "ended_at": item.ended_at,
            "ai_evaluation": ai_eval,
        },
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "confidence": e.confidence,
                "details": e.details_json,
                "created_at": e.created_at,
            }
            for e in events
        ],
        "evidence": [
            {
                "id": ev.id,
                "event_id": ev.event_id,
                "evidence_type": ev.evidence_type,
                "file_url": resolve_media_url(ev.file_url),
                "storage_ref": ev.file_url,
                "mime_type": ev.mime_type,
                "size_bytes": ev.size_bytes,
                "created_at": ev.created_at,
            }
            for ev in evidence
        ],
    }


@router.get("/admin/sessions")
def admin_sessions(
    flagged_only: bool = True,
    status: str | None = None,
    review_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    query = select(ProctorSession, User).join(User, User.id == ProctorSession.actor_user_id)
    if flagged_only:
        query = query.where(ProctorSession.is_flagged.is_(True))
    if status:
        query = query.where(ProctorSession.status == status)
    if review_status:
        query = query.where(ProctorSession.admin_review_status == review_status)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(ProctorSession.started_at.desc()).offset((page - 1) * page_size).limit(page_size),
    ).all()
    items = []
    for sess, user in rows:
        ev_count = db.scalar(select(func.count(ProctorEvent.id)).where(ProctorEvent.session_id == sess.id)) or 0
        evidence_count = db.scalar(select(func.count(ProctorEvidence.id)).where(ProctorEvidence.session_id == sess.id)) or 0
        ai_eval = evaluate_proctor_session(db, sess) if sess.status == "completed" else None
        items.append(
            {
                "session_id": sess.id,
                "session_code": sess.session_code,
                "mode": sess.mode,
                "status": sess.status,
                "actor_user_id": sess.actor_user_id,
                "actor_name": user.full_name,
                "actor_email": user.email,
                "exam_id": sess.exam_id,
                "attempt_id": sess.attempt_id,
                "warning_count": sess.warning_count,
                "risk_score": sess.risk_score,
                "is_flagged": sess.is_flagged,
                "admin_review_status": sess.admin_review_status,
                "events_count": ev_count,
                "evidence_count": evidence_count,
                "started_at": sess.started_at,
                "ended_at": sess.ended_at,
                "ai_decision": (ai_eval or {}).get("decision"),
                "ai_probability": (ai_eval or {}).get("final_probability"),
            },
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.get("/admin/training-reviews")
def admin_list_training_reviews(
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """All saved Pass/Fail proctor training labels (preview + student attempts), newest first."""
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    total = int(db.scalar(select(func.count(ProctorTrainingFeedback.id))) or 0)
    rows = db.execute(
        select(
            ProctorTrainingFeedback,
            User,
            func.coalesce(ProctorSession.exam_id, ExamAttempt.exam_id).label("resolved_exam_id"),
            ProctorSession.mode.label("session_mode"),
        )
        .join(User, User.id == ProctorTrainingFeedback.actor_user_id)
        .outerjoin(ProctorSession, ProctorSession.id == ProctorTrainingFeedback.session_id)
        .outerjoin(ExamAttempt, ExamAttempt.id == ProctorTrainingFeedback.attempt_id)
        .order_by(ProctorTrainingFeedback.created_at.desc(), ProctorTrainingFeedback.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size),
    ).all()
    items = []
    for fb, user, resolved_exam_id, session_mode in rows:
        context = "preview" if fb.attempt_id is None else "attempt"
        items.append(
            {
                "id": fb.id,
                "created_at": fb.created_at,
                "actor_user_id": fb.actor_user_id,
                "actor_name": user.full_name,
                "actor_email": user.email,
                "attempt_id": fb.attempt_id,
                "session_id": fb.session_id,
                "exam_id": int(resolved_exam_id) if resolved_exam_id is not None else None,
                "context": context,
                "session_mode": session_mode,
                "feedback_label": fb.feedback_label,
                "comment": fb.comment,
                "model_decision": fb.model_decision,
                "model_probability": fb.model_probability,
                "final_result_passed": fb.final_result_passed,
            },
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


@router.post("/admin/sessions/{session_id}/review")
def admin_review_session(
    session_id: int,
    payload: ProctorReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    item = _session_or_404(db, session_id)
    item.admin_review_status = payload.review_status
    item.admin_notes = payload.notes
    db.add(
        AuditLog(
            actor_user_id=current_user.id,
            action="proctor_session_review",
            target_type="proctor_session",
            target_id=item.id,
            details_json={"review_status": payload.review_status, "notes": payload.notes},
        ),
    )
    db.commit()
    return {
        "session_id": item.id,
        "admin_review_status": item.admin_review_status,
        "admin_notes": item.admin_notes,
    }
