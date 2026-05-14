from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import ProctorEvidence, ProctorEvent, ProctorSession, ProctorTrainingFeedback


@dataclass
class ProctorRetentionResult:
    cutoff_iso: str
    days: int
    sessions_deleted: int
    evidence_rows_deleted: int
    local_files_deleted: int


def run_proctor_retention_cleanup(db: Session, days: int = 30) -> ProctorRetentionResult:
    keep_days = max(7, min(3650, int(days)))
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    old_sessions = list(
        db.scalars(
            select(ProctorSession).where(
                and_(
                    ProctorSession.ended_at.is_not(None),
                    ProctorSession.ended_at < cutoff,
                    ProctorSession.status.in_(["completed", "terminated"]),
                ),
            ),
        ).all(),
    )
    session_ids = [int(s.id) for s in old_sessions]
    evidences_deleted = 0
    files_deleted = 0
    if session_ids:
        evidence_rows = list(
            db.scalars(select(ProctorEvidence).where(ProctorEvidence.session_id.in_(session_ids))).all(),
        )
        for ev in evidence_rows:
            try:
                url = str(ev.file_url or "")
                if url.startswith("/media/"):
                    rel = url[len("/media/"):].lstrip("/")
                    fpath = Path(get_settings().resolved_media_dir) / rel
                    if fpath.exists():
                        fpath.unlink(missing_ok=True)
                        files_deleted += 1
            except Exception:
                pass
        evidences_deleted = len(evidence_rows)
        db.query(ProctorEvidence).filter(ProctorEvidence.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(ProctorEvent).filter(ProctorEvent.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(ProctorTrainingFeedback).filter(ProctorTrainingFeedback.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(ProctorSession).filter(ProctorSession.id.in_(session_ids)).delete(synchronize_session=False)
        db.commit()
    return ProctorRetentionResult(
        cutoff_iso=cutoff.isoformat(),
        days=keep_days,
        sessions_deleted=len(session_ids),
        evidence_rows_deleted=evidences_deleted,
        local_files_deleted=files_deleted,
    )

