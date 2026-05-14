from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import ProctorEvidence, ProctorEvent, ProctorSession

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover
    joblib = None

try:
    import torch  # type: ignore
except Exception:  # pragma: no cover
    torch = None


_MODEL_CACHE: dict[str, Any] = {}
_RULES_CACHE: dict[str, Any] = {}
_EVENT_FEATURE_TYPES: list[str] = sorted(
    [
        "attention_challenge_failed",
        "background_voice_detected",
        "behavior_signature_drift",
        "face_identity_mismatch",
        "hand_near_face_repeated",
        "loud_voice_detected",
        "mobile_phone_detected",
        "multiple_faces_detected",
        "reading_aloud_detected",
        "side_glance_detected",
        "side_hand_activity_detected",
        "window_focus_lost",
        "gaze_pattern_review_flag",
    ],
)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _cache_key_for_path(name: str, path: Path) -> str:
    try:
        stat = path.stat()
        return f"{name}:{stat.st_mtime_ns}:{stat.st_size}"
    except FileNotFoundError:
        return f"{name}:missing"


def _load_rules() -> dict[str, Any]:
    path = Path("data/proctoring/models/supervised/deduction_rules.json")
    key = _cache_key_for_path("rules", path)
    cached = _RULES_CACHE.get(key)
    if cached is not None:
        return cached
    _RULES_CACHE.clear()
    if not path.exists():
        data = {
            "model": "logistic",
            "manual_review_threshold": 0.65,
            "warning_threshold": 0.45,
            "critical_threshold": 0.85,
            "auto_deduction_enabled": False,
            "deduction_policy": {
                "per_warning_pct": 0,
                "high_risk_event_pct": 0,
                "max_total_deduction_pct": 0,
            },
            "guardrails": {
                "require_two_signals": True,
                "require_min_confidence": 0.70,
                "always_manual_review_if_critical": True,
                "min_holdout_for_auto_deduction": 100,
            },
        }
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    _RULES_CACHE[key] = data
    return data


def _load_bundle() -> dict[str, Any] | None:
    path = Path("data/proctoring/models/supervised/supervised_bundle.joblib")
    key = _cache_key_for_path("bundle", path)
    cached = _MODEL_CACHE.get(key)
    if key in _MODEL_CACHE:
        return cached
    _MODEL_CACHE.clear()
    if joblib is None:
        _MODEL_CACHE[key] = None
        return None
    if not path.exists():
        _MODEL_CACHE[key] = None
        return None
    try:
        bundle = joblib.load(path)
    except Exception:
        bundle = None
    _MODEL_CACHE[key] = bundle
    return bundle


def reset_proctor_model_cache() -> None:
    _MODEL_CACHE.clear()
    _RULES_CACHE.clear()


def get_proctor_model_status() -> dict[str, Any]:
    bundle_path = Path("data/proctoring/models/supervised/supervised_bundle.joblib")
    rules_path = Path("data/proctoring/models/supervised/deduction_rules.json")
    bundle = _load_bundle()
    rules = _load_rules()
    model_names = sorted(list((bundle or {}).get("models", {}).keys()))
    feature_space = str((bundle or {}).get("feature_space") or "legacy_image_v1")
    meta = (bundle or {}).get("meta") or {}
    return {
        "bundle_path": str(bundle_path.resolve()),
        "bundle_exists": bundle_path.exists(),
        "bundle_loaded": bundle is not None,
        "rules_path": str(rules_path.resolve()),
        "rules_exists": rules_path.exists(),
        "selected_model": str(rules.get("model", "logistic")),
        "feature_space": feature_space,
        "trained_at": meta.get("trained_at"),
        "available_models": model_names,
        "auto_deduction_enabled": bool(rules.get("auto_deduction_enabled", False)),
        "thresholds": {
            "warning_threshold": _safe_float(rules.get("warning_threshold"), 0.45),
            "manual_review_threshold": _safe_float(rules.get("manual_review_threshold"), 0.65),
            "critical_threshold": _safe_float(rules.get("critical_threshold"), 0.85),
        },
    }


def _extract_image_features(img: np.ndarray) -> np.ndarray:
    if cv2 is None or np is None:
        raise RuntimeError("opencv is not installed")
    img = cv2.resize(img, (320, 180))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h_mean = float(np.mean(hsv[:, :, 0]))
    s_mean = float(np.mean(hsv[:, :, 1]))
    v_mean = float(np.mean(hsv[:, :, 2]))
    v_std = float(np.std(hsv[:, :, 2]))
    edge = cv2.Canny(gray, 80, 160)
    edge_ratio = float(np.mean(edge > 0))
    return np.array([h_mean, s_mean, v_mean, v_std, edge_ratio], dtype=np.float32)


def _session_feature_vector(db: Session, sess: ProctorSession) -> np.ndarray | None:
    if cv2 is None or np is None:
        return None
    settings = get_settings()
    media_root = Path(settings.resolved_media_dir).resolve()
    evidence_rows = list(
        db.scalars(
            select(ProctorEvidence)
            .where(ProctorEvidence.session_id == sess.id)
            .order_by(ProctorEvidence.created_at.asc()),
        ).all(),
    )
    frame_feats: list[np.ndarray] = []
    for ev in evidence_rows:
        if ev.evidence_type not in {"image", "video"}:
            continue
        rel = str(ev.file_url or "").strip().lstrip("/")
        if rel.startswith("media/"):
            rel = rel[len("media/"):]
        path = (media_root / rel).resolve()
        if not path.exists() or not path.is_file():
            continue
        try:
            img = cv2.imread(str(path))
            if img is None:
                continue
            frame_feats.append(_extract_image_features(img))
        except Exception:
            continue
    if not frame_feats:
        return None
    mat = np.stack(frame_feats, axis=0)
    return np.concatenate([np.mean(mat, axis=0), np.std(mat, axis=0)], axis=0).astype(np.float32)


def _event_feature_vector(db: Session, sess: ProctorSession) -> np.ndarray | None:
    if np is None:
        return None
    rows = db.execute(
        select(ProctorEvent.event_type, func.count(ProctorEvent.id))
        .where(ProctorEvent.session_id == sess.id)
        .group_by(ProctorEvent.event_type),
    ).all()
    counts: dict[str, int] = {str(ev_type): int(cnt or 0) for ev_type, cnt in rows}
    high_risk_events = float(
        sum(
            int(counts.get(k, 0))
            for k in ("mobile_phone_detected", "multiple_faces_detected", "face_identity_mismatch", "attention_challenge_failed")
        ),
    )
    event_signal_score = min(
        1.0,
        (
            (0.55 if counts.get("mobile_phone_detected", 0) else 0.0)
            + (0.32 if counts.get("attention_challenge_failed", 0) else 0.0)
            + (0.28 if counts.get("behavior_signature_drift", 0) else 0.0)
            + (0.30 if counts.get("reading_aloud_detected", 0) else 0.0)
            + (0.26 if counts.get("background_voice_detected", 0) else 0.0)
            + (0.35 if counts.get("multiple_faces_detected", 0) else 0.0)
            + (0.30 if counts.get("face_identity_mismatch", 0) else 0.0)
        ),
    )
    duration_minutes = 0.0
    if sess.started_at:
        end = sess.ended_at or sess.started_at
        duration_minutes = max(0.0, min(180.0, float((end - sess.started_at).total_seconds()) / 60.0))
    values: list[float] = [
        float(sess.warning_count or 0),
        float(max(0.0, min(100.0, float(sess.risk_score or 0.0))) / 100.0),
        float(duration_minutes),
        float(high_risk_events),
        float(event_signal_score),
    ]
    for event_type in _EVENT_FEATURE_TYPES:
        values.append(float(counts.get(event_type, 0)))
    return np.asarray(values, dtype=np.float32)


def _count_high_risk_events(db: Session, sess: ProctorSession) -> int:
    return int(
        db.scalar(
            select(func.count(ProctorEvent.id)).where(
                ProctorEvent.session_id == sess.id,
                ProctorEvent.severity.in_(["critical", "warning"]),
            ),
        )
        or 0,
    )


def _count_event_type(db: Session, sess: ProctorSession, event_type: str) -> int:
    return int(
        db.scalar(
            select(func.count(ProctorEvent.id)).where(
                ProctorEvent.session_id == sess.id,
                ProctorEvent.event_type == event_type,
            ),
        )
        or 0,
    )


def _weighted_event_signals(db: Session, sess: ProctorSession) -> tuple[float, dict[str, int], list[str]]:
    weighted_events = {
        "mobile_phone_detected": 0.55,
        "attention_challenge_failed": 0.32,
        "behavior_signature_drift": 0.28,
        "behavior_signature_drift_detail": 0.08,
        "gaze_pattern_review_flag": 0.36,
        "gaze_soft_attention_notice": 0.1,
        "gaze_suspicion_internal": 0.06,
        "gaze_suspicion_silent_log": 0.03,
        "gaze_outside_allowed_ui": 0.08,
        "suspicious_zone_revisited": 0.1,
        "static_gaze_suspicious_zone": 0.07,
        "fast_correct_after_suspicion": 0.12,
        "cross_question_zone_pattern": 0.14,
        "gaze_layer1_observation": 0.01,
        "gaze_suspicion_layer2": 0.0,
        "side_glance_detected": 0.20,
        "side_hand_activity_detected": 0.22,
        "hand_near_face_repeated": 0.18,
        "moved_far_from_screen": 0.12,
        "reading_aloud_detected": 0.30,
        "background_voice_detected": 0.26,
        "loud_voice_detected": 0.26,
        "external_voice_detected": 0.22,
        "look_away_over_2s": 0.10,
        "multiple_faces_detected": 0.35,
        "face_identity_mismatch": 0.30,
        "face_not_visible": 0.08,
        "unusual_movement": 0.05,
        "window_focus_lost": 0.12,
        "proctor_warning": 0.05,
    }
    counts: dict[str, int] = {}
    triggered: list[str] = []
    score = 0.0
    for event_type, weight in weighted_events.items():
        count = _count_event_type(db, sess, event_type)
        if count <= 0:
            continue
        counts[event_type] = count
        triggered.append(event_type)
        # Saturating contribution so repeated events matter without exploding the score.
        score += min(weight, weight * (0.65 + (0.35 * min(count, 3))))
    return min(1.0, score), counts, triggered


def _predict_probability(feature_vec: np.ndarray, rules: dict[str, Any]) -> tuple[float | None, str]:
    if np is None:
        return None, "numpy_missing"
    bundle = _load_bundle()
    if not bundle:
        return None, "model_bundle_missing"

    pre = bundle.get("pre")
    models = bundle.get("models") or {}
    model_name = str(rules.get("model", "logistic"))
    model = models.get(model_name) or models.get("logistic")
    selected_name = model_name if model is not None else "logistic"
    if model is None:
        return None, "chosen_model_missing"

    try:
        x = np.asarray(feature_vec, dtype=np.float32).reshape(1, -1)
        if isinstance(pre, dict) and pre.get("type") == "standard_scale_v1":
            mean = np.asarray(pre.get("mean") or [], dtype=np.float32).reshape(1, -1)
            std = np.asarray(pre.get("std") or [], dtype=np.float32).reshape(1, -1)
            std = np.where(std <= 1e-7, 1.0, std)
            if mean.shape[1] == x.shape[1]:
                xt = (x - mean) / std
            else:
                xt = x
        else:
            xt = pre.transform(x) if pre is not None else x
        if hasattr(model, "predict_proba"):
            p = float(model.predict_proba(xt)[0][1])
            return p, selected_name
        if isinstance(model, dict) and model.get("type") == "linear_logistic_v1":
            w = np.asarray(model.get("weights") or [], dtype=np.float32)
            b = float(model.get("bias") or 0.0)
            if w.shape[0] == xt.shape[1]:
                z = float((xt[0] @ w) + b)
                z = max(-40.0, min(40.0, z))
                p = float(1.0 / (1.0 + np.exp(-z)))
                return p, selected_name
        if torch is not None and hasattr(model, "eval"):
            model.eval()
            with torch.no_grad():
                tx = torch.tensor(xt, dtype=torch.float32).unsqueeze(1)
                logits = model(tx)
                p = float(torch.sigmoid(logits).squeeze().item())
                return p, selected_name
    except Exception:
        return None, "prediction_failed"
    return None, "unsupported_model"


def evaluate_proctor_session(db: Session, sess: ProctorSession) -> dict[str, Any]:
    rules = _load_rules()
    warning_threshold = _safe_float(rules.get("warning_threshold"), 0.45)
    review_threshold = _safe_float(rules.get("manual_review_threshold"), 0.65)
    critical_threshold = _safe_float(rules.get("critical_threshold"), 0.85)
    auto_deduction_enabled = bool(rules.get("auto_deduction_enabled", False))
    policy = rules.get("deduction_policy") or {}
    per_warning_pct = _safe_float(policy.get("per_warning_pct"), 0.0)
    high_risk_event_pct = _safe_float(policy.get("high_risk_event_pct"), 0.0)
    max_total_deduction_pct = _safe_float(policy.get("max_total_deduction_pct"), 0.0)

    warnings = int(sess.warning_count or 0)
    high_risk_events = _count_high_risk_events(db, sess)
    mobile_events = _count_event_type(db, sess, "mobile_phone_detected")
    voice_events = _count_event_type(db, sess, "external_voice_detected")
    reading_aloud_events = _count_event_type(db, sess, "reading_aloud_detected")
    background_voice_events = _count_event_type(db, sess, "background_voice_detected")
    lookaway_events = _count_event_type(db, sess, "look_away_over_2s")
    gaze_related_events = int(
        db.scalar(
            select(func.count(ProctorEvent.id)).where(
                and_(
                    ProctorEvent.session_id == sess.id,
                    or_(
                        ProctorEvent.event_type.like("gaze_%"),
                        ProctorEvent.event_type == "look_away_over_2s",
                        ProctorEvent.event_type == "pupil_drift_non_text_zone",
                    ),
                ),
            ),
        )
        or 0
    )
    event_signal_score, event_signal_counts, triggered_signals = _weighted_event_signals(db, sess)
    base_event_score = min(1.0, max(event_signal_score, (warnings * 0.15) + (high_risk_events * 0.04)))

    bundle = _load_bundle() or {}
    feature_space = str(bundle.get("feature_space") or "legacy_image_v1")
    if feature_space == "event_risk_v1":
        feature_vec = _event_feature_vector(db, sess)
    else:
        feature_vec = _session_feature_vector(db, sess)
    ml_prob, model_name = (None, "not_available")
    if feature_vec is not None:
        ml_prob, model_name = _predict_probability(feature_vec, rules)

    if ml_prob is None:
        final_prob = float(base_event_score)
    else:
        final_prob = float(max(0.0, min(1.0, (0.65 * ml_prob) + (0.35 * base_event_score))))

    # Explicitly promote sessions with strong, rule-specific evidence even if the model is uncertain.
    if mobile_events >= 3:
        final_prob = max(final_prob, 0.97)
    if event_signal_counts.get("attention_challenge_failed", 0) >= 1:
        final_prob = max(final_prob, 0.83)
    if reading_aloud_events >= 1:
        final_prob = max(final_prob, 0.86)
    if background_voice_events >= 1 and voice_events >= 1:
        final_prob = max(final_prob, 0.87)
    if event_signal_counts.get("behavior_signature_drift", 0) >= 1 and (
        event_signal_counts.get("side_glance_detected", 0) >= 1 or event_signal_counts.get("side_hand_activity_detected", 0) >= 1
    ):
        final_prob = max(final_prob, 0.88)
    if event_signal_counts.get("loud_voice_detected", 0) >= 1 and voice_events >= 1:
        final_prob = max(final_prob, 0.84)

    if final_prob >= critical_threshold:
        decision = "critical"
    elif final_prob >= review_threshold:
        decision = "manual_review"
    elif final_prob >= warning_threshold:
        decision = "warning"
    else:
        decision = "clear"

    is_flagged = bool(decision in {"critical", "manual_review"} or gaze_related_events > 5 or warnings >= 5)
    hard_fail = bool(mobile_events >= 3 or voice_events >= 3)
    hard_fail_reason = None
    if mobile_events >= 3:
        hard_fail_reason = "Mobile phone usage threshold reached during assessment."
    elif voice_events >= 3:
        hard_fail_reason = "Repeated external voice activity detected."
    deduction_pct = 0.0
    deduction_mode = "none"
    if auto_deduction_enabled:
        deduction_pct = (warnings * per_warning_pct) + (high_risk_events * high_risk_event_pct)
        if event_signal_counts.get("behavior_signature_drift", 0) >= 1:
            deduction_pct += 4.0
        if event_signal_counts.get("attention_challenge_failed", 0) >= 1:
            deduction_pct += 5.0
        if reading_aloud_events >= 1:
            deduction_pct += 5.0
        if background_voice_events >= 1:
            deduction_pct += 4.0
        if event_signal_counts.get("side_glance_detected", 0) >= 1:
            deduction_pct += 3.0
        if event_signal_counts.get("side_hand_activity_detected", 0) >= 1:
            deduction_pct += 3.0
        if event_signal_counts.get("loud_voice_detected", 0) >= 1:
            deduction_pct += 4.0
        if max_total_deduction_pct > 0:
            deduction_pct = min(deduction_pct, max_total_deduction_pct)
        if deduction_pct > 0:
            deduction_mode = "auto"
    else:
        # Conservative but enforceable fallback: if behavior is critical or reaches max warnings,
        # apply a fixed provisional deduction and force manual review.
        if decision == "critical" or warnings >= 5:
            deduction_pct = 10.0
            if event_signal_counts.get("behavior_signature_drift", 0) >= 1:
                deduction_pct = max(deduction_pct, 12.0)
            if event_signal_counts.get("attention_challenge_failed", 0) >= 1:
                deduction_pct = max(deduction_pct, 14.0)
            if reading_aloud_events >= 1:
                deduction_pct = max(deduction_pct, 14.0)
            if background_voice_events >= 1:
                deduction_pct = max(deduction_pct, 12.0)
            if event_signal_counts.get("loud_voice_detected", 0) >= 1:
                deduction_pct = max(deduction_pct, 12.0)
            if max_total_deduction_pct > 0:
                deduction_pct = min(deduction_pct, max_total_deduction_pct)
            deduction_mode = "enforcement"
    deduction_pct = float(max(0.0, deduction_pct))

    return {
        "model_used": model_name,
        "ml_probability": ml_prob,
        "event_probability": float(base_event_score),
        "final_probability": float(final_prob),
        "decision": decision,
        "thresholds": {
            "warning_threshold": warning_threshold,
            "manual_review_threshold": review_threshold,
            "critical_threshold": critical_threshold,
        },
        "warnings": warnings,
        "gaze_related_events": gaze_related_events,
        "high_risk_events": high_risk_events,
        "mobile_events": mobile_events,
        "voice_events": voice_events,
        "reading_aloud_events": reading_aloud_events,
        "background_voice_events": background_voice_events,
        "lookaway_events": lookaway_events,
        "event_signal_score": float(event_signal_score),
        "event_signal_counts": event_signal_counts,
        "triggered_signals": triggered_signals,
        "auto_deduction_enabled": auto_deduction_enabled,
        "deduction_pct": deduction_pct,
        "deduction_mode": deduction_mode,
        "review_required": decision in {"warning", "manual_review", "critical"},
        "is_flagged": is_flagged,
        "hard_fail": hard_fail,
        "hard_fail_reason": hard_fail_reason,
    }
