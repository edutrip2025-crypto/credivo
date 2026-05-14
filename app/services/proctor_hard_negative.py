from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import ProctorEvent, ProctorSession, ProctorTrainingFeedback


HARD_NEGATIVE_DATA_PATH = Path("data/proctoring/processed/hard_negatives.json")
SUSPICIOUS_DECISIONS = {"warning", "manual_review", "critical"}


def _load_existing_records() -> list[dict[str, Any]]:
    if not HARD_NEGATIVE_DATA_PATH.exists():
        return []
    try:
        raw = json.loads(HARD_NEGATIVE_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict):
            out.append(row)
    return out


def _save_records(rows: list[dict[str, Any]]) -> None:
    HARD_NEGATIVE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    HARD_NEGATIVE_DATA_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def load_curated_hard_negative_records(limit: int = 0) -> list[dict[str, Any]]:
    rows = _load_existing_records()
    if limit > 0:
        return rows[:limit]
    return rows


def summarize_curated_hard_negatives() -> dict[str, Any]:
    rows = _load_existing_records()
    session_ids = {int(r.get("session_id") or 0) for r in rows if int(r.get("session_id") or 0) > 0}
    return {
        "path": str(HARD_NEGATIVE_DATA_PATH),
        "exists": HARD_NEGATIVE_DATA_PATH.exists(),
        "records": int(len(rows)),
        "unique_sessions": int(len(session_ids)),
    }


def ingest_hard_negative_sessions_from_feedback(
    db: Session,
    lookback_days: int = 45,
    limit: int = 1000,
    min_model_probability: float = 0.45,
    include_preview_sessions: bool = False,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(lookback_days)))
    query = (
        select(ProctorTrainingFeedback, ProctorSession)
        .join(ProctorSession, ProctorSession.id == ProctorTrainingFeedback.session_id)
        .where(
            ProctorTrainingFeedback.session_id.is_not(None),
            ProctorTrainingFeedback.feedback_label == "incorrect",
            ProctorSession.status == "completed",
            ProctorSession.started_at >= cutoff,
        )
        .order_by(ProctorTrainingFeedback.created_at.desc(), ProctorTrainingFeedback.id.desc())
        .limit(max(1, int(limit)) * 3)
    )
    rows = db.execute(query).all()
    latest_by_session: dict[int, tuple[ProctorTrainingFeedback, ProctorSession]] = {}
    for fb, sess in rows:
        sid = int(sess.id)
        if sid in latest_by_session:
            continue
        latest_by_session[sid] = (fb, sess)
        if len(latest_by_session) >= max(1, int(limit)):
            break

    session_ids = list(latest_by_session.keys())
    event_rows = db.execute(
        select(ProctorEvent.session_id, ProctorEvent.event_type, func.count(ProctorEvent.id))
        .where(ProctorEvent.session_id.in_(session_ids) if session_ids else False)
        .group_by(ProctorEvent.session_id, ProctorEvent.event_type),
    ).all()
    event_counts_by_session: dict[int, dict[str, int]] = {}
    for session_id, event_type, cnt in event_rows:
        sid = int(session_id)
        if sid not in event_counts_by_session:
            event_counts_by_session[sid] = {}
        event_counts_by_session[sid][str(event_type or "")] = int(cnt or 0)

    existing = _load_existing_records()
    by_session: dict[int, dict[str, Any]] = {}
    for row in existing:
        sid = int(row.get("session_id") or 0)
        if sid > 0:
            by_session[sid] = row

    inserted = 0
    updated = 0
    skipped = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for sid, pair in latest_by_session.items():
        fb, sess = pair
        if str(sess.mode or "").lower() == "preview" and not include_preview_sessions:
            skipped += 1
            continue
        decision = str(fb.model_decision or "").strip().lower()
        model_probability = float(fb.model_probability or 0.0)
        warning_count = int(sess.warning_count or 0)
        risk_score = float(sess.risk_score or 0.0)
        suspicious_like = (
            decision in SUSPICIOUS_DECISIONS
            or model_probability >= float(min_model_probability)
            or warning_count >= 1
            or risk_score >= 20.0
        )
        if not suspicious_like:
            skipped += 1
            continue
        started_at = sess.started_at
        ended_at = sess.ended_at or started_at
        duration_seconds = 0
        if started_at and ended_at:
            duration_seconds = max(0, int((ended_at - started_at).total_seconds()))
        row = {
            "session_id": sid,
            "source": "real_session_feedback",
            "label": 0,
            "sample_weight_hint": 2.6,
            "model_decision": decision or None,
            "model_probability": model_probability,
            "feedback_label": str(fb.feedback_label or "").strip().lower(),
            "feedback_comment": (str(fb.comment or "").strip() or None),
            "warning_count": warning_count,
            "risk_score": risk_score,
            "duration_seconds": duration_seconds,
            "event_counts": event_counts_by_session.get(sid, {}),
            "mode": str(sess.mode or "").strip().lower(),
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        prev = by_session.get(sid)
        if prev:
            row["created_at"] = str(prev.get("created_at") or now_iso)
            by_session[sid] = row
            updated += 1
        else:
            by_session[sid] = row
            inserted += 1

    merged = sorted(
        by_session.values(),
        key=lambda x: str(x.get("updated_at") or ""),
        reverse=True,
    )
    _save_records(merged)
    return {
        "status": "ok",
        "path": str(HARD_NEGATIVE_DATA_PATH),
        "lookback_days": int(lookback_days),
        "requested_limit": int(limit),
        "min_model_probability": float(min_model_probability),
        "include_preview_sessions": bool(include_preview_sessions),
        "candidates_seen": int(len(latest_by_session)),
        "inserted": int(inserted),
        "updated": int(updated),
        "skipped": int(skipped),
        "total_records": int(len(merged)),
    }
