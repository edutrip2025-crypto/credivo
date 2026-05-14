from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import ProctorEvent, ProctorSession, ProctorTrainingFeedback
from app.services.proctor_hard_negative import load_curated_hard_negative_records
from app.services.proctoring_ai import evaluate_proctor_session

try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover
    joblib = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None


EVENT_WEIGHTS: dict[str, float] = {
    "mobile_phone_detected": 0.55,
    "attention_challenge_failed": 0.32,
    "behavior_signature_drift": 0.28,
    "gaze_pattern_review_flag": 0.36,
    "side_glance_detected": 0.20,
    "side_hand_activity_detected": 0.22,
    "hand_near_face_repeated": 0.18,
    "reading_aloud_detected": 0.30,
    "background_voice_detected": 0.26,
    "loud_voice_detected": 0.26,
    "multiple_faces_detected": 0.35,
    "face_identity_mismatch": 0.30,
    "window_focus_lost": 0.12,
}

FEATURE_EVENT_TYPES: list[str] = sorted(EVENT_WEIGHTS.keys())


@dataclass
class TrainConfig:
    minimum_samples: int = 30
    validation_split: float = 0.2
    target_recall: float = 0.92
    max_false_positive_rate: float = 0.30
    strict_mode: bool = True
    seed: int = 42
    class_balance_strength: float = 1.0
    hard_negative_weight: float = 2.0
    hard_positive_weight: float = 1.6
    hard_example_min_prob: float = 0.55
    curated_hard_negative_weight: float = 2.6
    max_curated_hard_negatives: int = 800


def _sigmoid(x):
    if np is None:
        raise RuntimeError("numpy is required")
    x = np.clip(x, -40, 40)
    return 1.0 / (1.0 + np.exp(-x))


def _safe_ratio(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return float(num / den)


def _metrics_at_threshold(y_true, y_prob, threshold: float) -> dict[str, float]:
    if np is None:
        raise RuntimeError("numpy is required")
    pred = (y_prob >= threshold).astype(np.int32)
    tp = int(np.sum((pred == 1) & (y_true == 1)))
    fp = int(np.sum((pred == 1) & (y_true == 0)))
    tn = int(np.sum((pred == 0) & (y_true == 0)))
    fn = int(np.sum((pred == 0) & (y_true == 1)))
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    fpr = _safe_ratio(fp, fp + tn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "fpr": float(fpr),
        "f1": float(f1),
        "tp": float(tp),
        "fp": float(fp),
        "tn": float(tn),
        "fn": float(fn),
    }


def _choose_threshold(y_true, y_prob, target_recall: float, max_fpr: float) -> dict[str, float]:
    if np is None:
        raise RuntimeError("numpy is required")
    thresholds = np.linspace(0.15, 0.92, 156)
    valid: list[dict[str, float]] = []
    all_scores: list[dict[str, float]] = []
    for t in thresholds:
        m = _metrics_at_threshold(y_true, y_prob, float(t))
        all_scores.append(m)
        if m["recall"] >= target_recall and m["fpr"] <= max_fpr:
            valid.append(m)
    if valid:
        # Strict bias: among valid points prefer lower FPR, then higher recall and precision.
        valid.sort(key=lambda x: (x["fpr"], -x["recall"], -x["precision"]))
        return valid[0]
    # Fallback: maximize F2 score for recall-priority behavior.
    best = None
    best_f2 = -1.0
    for m in all_scores:
        beta2 = 4.0
        p = m["precision"]
        r = m["recall"]
        f2 = _safe_ratio((1 + beta2) * p * r, (beta2 * p) + r)
        if f2 > best_f2:
            best_f2 = f2
            best = m
    return best or _metrics_at_threshold(y_true, y_prob, 0.5)


def _roc_auc(y_true, y_prob) -> float:
    if np is None:
        raise RuntimeError("numpy is required")
    order = np.argsort(y_prob)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(y_prob))
    pos = y_true == 1
    n_pos = int(np.sum(pos))
    n_neg = int(np.sum(~pos))
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum_pos = float(np.sum(ranks[pos]))
    auc = (rank_sum_pos - (n_pos * (n_pos - 1) / 2.0)) / float(n_pos * n_neg)
    return float(max(0.0, min(1.0, auc)))


def _derive_truth_label(feedback_label: str, model_decision: str | None) -> int:
    suspicious_pred = str(model_decision or "").strip().lower() in {"warning", "manual_review", "critical"}
    is_correct = str(feedback_label or "").strip().lower() == "correct"
    if is_correct:
        return 1 if suspicious_pred else 0
    return 0 if suspicious_pred else 1


def _duration_seconds(sess: ProctorSession) -> float:
    start = sess.started_at
    end = sess.ended_at or start
    if not start or not end:
        return 0.0
    return max(0.0, float((end - start).total_seconds()))


def _event_signal_score(counts: dict[str, int]) -> float:
    score = 0.0
    for event_type, weight in EVENT_WEIGHTS.items():
        c = int(counts.get(event_type, 0))
        if c <= 0:
            continue
        score += min(weight, weight * (0.65 + (0.35 * min(c, 3))))
    return float(min(1.0, score))


def _build_feature_row(sess: ProctorSession, event_counts: dict[str, int]) -> list[float]:
    high_risk_events = float(
        sum(
            int(event_counts.get(k, 0))
            for k in ("mobile_phone_detected", "multiple_faces_detected", "face_identity_mismatch", "attention_challenge_failed")
        ),
    )
    row: list[float] = [
        float(sess.warning_count or 0),
        float(max(0.0, min(100.0, float(sess.risk_score or 0.0))) / 100.0),
        float(min(180.0, _duration_seconds(sess) / 60.0)),
        high_risk_events,
        _event_signal_score(event_counts),
    ]
    for event_type in FEATURE_EVENT_TYPES:
        row.append(float(event_counts.get(event_type, 0)))
    return row


def _feature_names() -> list[str]:
    base = ["warning_count", "risk_score_norm", "duration_minutes", "high_risk_events", "event_signal_score"]
    return base + [f"ev__{k}" for k in FEATURE_EVENT_TYPES]


def _stratified_split(y, validation_split: float, seed: int):
    if np is None:
        raise RuntimeError("numpy is required")
    rng = np.random.default_rng(seed)
    idx = np.arange(len(y))
    pos = idx[y == 1]
    neg = idx[y == 0]
    rng.shuffle(pos)
    rng.shuffle(neg)
    pos_val = max(1, int(math.ceil(len(pos) * validation_split))) if len(pos) > 1 else 1
    neg_val = max(1, int(math.ceil(len(neg) * validation_split))) if len(neg) > 1 else 1
    val_idx = np.concatenate([pos[:pos_val], neg[:neg_val]])
    val_set = set(int(i) for i in val_idx.tolist())
    train_idx = np.array([i for i in idx if int(i) not in val_set], dtype=np.int64)
    if len(train_idx) < 4 or len(val_idx) < 2:
        # Fallback to simple split if classes are tiny.
        rng.shuffle(idx)
        cut = max(1, int(len(idx) * (1.0 - validation_split)))
        train_idx = idx[:cut]
        val_idx = idx[cut:]
    return train_idx, val_idx


def _train_logistic_model(X_train, y_train, sample_w):
    if np is None:
        raise RuntimeError("numpy is required")
    n_features = X_train.shape[1]
    w = np.zeros((n_features,), dtype=np.float64)
    b = 0.0
    lr = 0.08
    l2 = 0.01
    sw_sum = max(1e-9, float(np.sum(sample_w)))
    for _ in range(1200):
        z = (X_train @ w) + b
        p = _sigmoid(z)
        err = p - y_train
        grad_w = (X_train.T @ (err * sample_w)) / sw_sum + (l2 * w)
        grad_b = float(np.sum(err * sample_w) / sw_sum)
        w -= lr * grad_w
        b -= lr * grad_b
    return w, b


def _class_balance_weights(y, strength: float):
    if np is None:
        raise RuntimeError("numpy is required")
    weights = np.ones((len(y),), dtype=np.float64)
    pos = max(1, int(np.sum(y == 1)))
    neg = max(1, int(np.sum(y == 0)))
    if pos == 0 or neg == 0:
        return weights
    ratio = float(max(pos, neg) / max(1, min(pos, neg)))
    ratio = float(max(1.0, min(8.0, ratio)))
    if strength <= 0:
        return weights
    scale = float(ratio ** max(0.0, min(1.5, strength)))
    if pos < neg:
        weights[y == 1] *= scale
    else:
        weights[y == 0] *= scale
    return weights


def _apply_hard_example_boost(
    X_train,
    y_train,
    sample_w,
    w,
    b,
    hard_negative_weight: float,
    hard_positive_weight: float,
    min_prob: float,
):
    if np is None:
        raise RuntimeError("numpy is required")
    train_prob = _sigmoid((X_train @ w) + b)
    boosted = sample_w.copy()
    hard_neg = (y_train == 0) & (train_prob >= min_prob)
    hard_pos = (y_train == 1) & (train_prob <= (1.0 - min_prob))
    if np.any(hard_neg):
        boosted[hard_neg] *= max(1.0, float(hard_negative_weight))
    if np.any(hard_pos):
        boosted[hard_pos] *= max(1.0, float(hard_positive_weight))
    return boosted, int(np.sum(hard_neg)), int(np.sum(hard_pos))


def _collect_event_counts(db: Session, session_ids: list[int]) -> dict[int, dict[str, int]]:
    if not session_ids:
        return {}
    rows = db.execute(
        select(ProctorEvent.session_id, ProctorEvent.event_type, func.count(ProctorEvent.id))
        .where(ProctorEvent.session_id.in_(session_ids))
        .group_by(ProctorEvent.session_id, ProctorEvent.event_type),
    ).all()
    out: dict[int, dict[str, int]] = {}
    for session_id, event_type, cnt in rows:
        sid = int(session_id)
        if sid not in out:
            out[sid] = {}
        out[sid][str(event_type or "")] = int(cnt or 0)
    return out


def _append_curated_hard_negative_rows(
    x_rows: list[list[float]],
    y_rows: list[int],
    sample_w: list[float],
    weight: float,
    max_rows: int,
) -> int:
    rows = load_curated_hard_negative_records(limit=max_rows)
    if not rows:
        return 0
    added = 0
    safe_w = float(max(1.0, min(12.0, weight)))
    for row in rows:
        counts_raw = row.get("event_counts") if isinstance(row, dict) else {}
        counts = counts_raw if isinstance(counts_raw, dict) else {}
        warning_count = float(row.get("warning_count") or 0.0)
        risk_score = float(row.get("risk_score") or 0.0)
        duration_seconds = float(row.get("duration_seconds") or 0.0)
        duration_minutes = max(0.0, min(180.0, duration_seconds / 60.0))
        high_risk_events = float(
            sum(
                int(counts.get(k, 0) or 0)
                for k in ("mobile_phone_detected", "multiple_faces_detected", "face_identity_mismatch", "attention_challenge_failed")
            ),
        )
        feature_row: list[float] = [
            warning_count,
            float(max(0.0, min(100.0, risk_score)) / 100.0),
            duration_minutes,
            high_risk_events,
            _event_signal_score({str(k): int(v or 0) for k, v in counts.items()}),
        ]
        for event_type in FEATURE_EVENT_TYPES:
            feature_row.append(float(int(counts.get(event_type, 0) or 0)))
        x_rows.append(feature_row)
        y_rows.append(0)
        sample_w.append(safe_w)
        added += 1
    return added


def _load_latest_feedback_per_session(db: Session) -> list[tuple[ProctorTrainingFeedback, ProctorSession]]:
    rows = db.execute(
        select(ProctorTrainingFeedback, ProctorSession)
        .join(ProctorSession, ProctorSession.id == ProctorTrainingFeedback.session_id)
        .where(
            ProctorTrainingFeedback.session_id.is_not(None),
            ProctorSession.status == "completed",
        )
        .order_by(ProctorTrainingFeedback.created_at.desc(), ProctorTrainingFeedback.id.desc()),
    ).all()
    latest: dict[int, tuple[ProctorTrainingFeedback, ProctorSession]] = {}
    for fb, sess in rows:
        sid = int(sess.id)
        if sid not in latest:
            latest[sid] = (fb, sess)
    return list(latest.values())


def _load_pseudo_labeled_sessions(db: Session, excluded_session_ids: set[int], limit: int = 300) -> list[tuple[ProctorSession, int]]:
    rows = list(
        db.scalars(
            select(ProctorSession)
            .where(
                ProctorSession.status == "completed",
                ProctorSession.id.not_in(list(excluded_session_ids)) if excluded_session_ids else True,
            )
            .order_by(ProctorSession.started_at.desc(), ProctorSession.id.desc())
            .limit(limit),
        ).all(),
    )
    out: list[tuple[ProctorSession, int]] = []
    for sess in rows:
        ev = evaluate_proctor_session(db, sess)
        decision = str((ev or {}).get("decision") or "").strip().lower()
        y = 1 if decision in {"warning", "manual_review", "critical"} else 0
        out.append((sess, y))
    return out


def _recalibrate_thresholds_only(db: Session, strict_mode: bool) -> dict[str, Any]:
    if np is None:
        raise RuntimeError("numpy is required")
    rows = list(
        db.scalars(
            select(ProctorSession)
            .where(ProctorSession.status == "completed")
            .order_by(ProctorSession.started_at.desc(), ProctorSession.id.desc())
            .limit(500),
        ).all(),
    )
    probs: list[float] = []
    for sess in rows:
        ev = evaluate_proctor_session(db, sess)
        probs.append(float((ev or {}).get("event_probability") or 0.0))
    if not probs:
        raise RuntimeError("No completed proctor sessions available for threshold recalibration.")
    arr = np.asarray(probs, dtype=np.float64)
    p70 = float(np.quantile(arr, 0.70))
    p90 = float(np.quantile(arr, 0.90))
    if strict_mode:
        manual = max(0.48, min(0.88, p70))
        warning = max(0.20, manual - 0.13)
        critical = min(0.97, max(manual + 0.14, p90))
    else:
        manual = max(0.52, min(0.90, p70 + 0.03))
        warning = max(0.24, manual - 0.10)
        critical = min(0.97, max(manual + 0.18, p90 + 0.04))
    if critical <= manual:
        critical = min(0.97, manual + 0.1)
    return {
        "rows_total": int(len(rows)),
        "warnings_only_recalibration": True,
        "distribution": {
            "p70": p70,
            "p90": p90,
        },
        "thresholds": {
            "warning_threshold": float(warning),
            "manual_review_threshold": float(manual),
            "critical_threshold": float(critical),
        },
    }


def train_proctor_model_from_feedback(db: Session, config: TrainConfig) -> dict[str, Any]:
    if np is None:
        raise RuntimeError("numpy is required. Install requirements-ml.txt")
    if joblib is None:
        raise RuntimeError("joblib is required. Install requirements-ml.txt")

    rows = _load_latest_feedback_per_session(db)
    feedback_only_count = len(rows)
    curated_hard_negative_count = 0

    session_ids = [int(sess.id) for _, sess in rows]
    event_counts_by_session = _collect_event_counts(db, session_ids)

    x_rows: list[list[float]] = []
    y_rows: list[int] = []
    sample_w: list[float] = []
    for fb, sess in rows:
        counts = event_counts_by_session.get(int(sess.id), {})
        x_rows.append(_build_feature_row(sess, counts))
        y_rows.append(_derive_truth_label(str(fb.feedback_label or ""), fb.model_decision))
        # Give slightly higher importance to "incorrect" feedback since it marks model mistakes.
        sample_w.append(1.35 if str(fb.feedback_label or "").strip().lower() == "incorrect" else 1.0)

    if len(x_rows) < config.minimum_samples:
        needed = max(0, config.minimum_samples - len(x_rows))
        pseudo = _load_pseudo_labeled_sessions(db, set(session_ids), limit=max(needed * 4, 80))
        pseudo_ids = [int(sess.id) for sess, _ in pseudo]
        pseudo_counts = _collect_event_counts(db, pseudo_ids)
        for sess, y in pseudo:
            counts = pseudo_counts.get(int(sess.id), {})
            x_rows.append(_build_feature_row(sess, counts))
            y_rows.append(int(y))
            # Low weight so pseudo labels never dominate explicit human feedback.
            sample_w.append(0.35)
            if len(x_rows) >= config.minimum_samples:
                break

    curated_hard_negative_count = _append_curated_hard_negative_rows(
        x_rows,
        y_rows,
        sample_w,
        config.curated_hard_negative_weight,
        config.max_curated_hard_negatives,
    )

    if len(x_rows) < config.minimum_samples:
        raise RuntimeError(
            f"Not enough sessions for training after pseudo-label fallback. Need {config.minimum_samples}, found {len(x_rows)}.",
        )

    X = np.asarray(x_rows, dtype=np.float64)
    y = np.asarray(y_rows, dtype=np.int32)
    sw = np.asarray(sample_w, dtype=np.float64)

    positives = int(np.sum(y == 1))
    negatives = int(np.sum(y == 0))
    if positives < 4 or negatives < 4:
        model_dir = Path("data/proctoring/models/supervised")
        model_dir.mkdir(parents=True, exist_ok=True)
        rules_path = model_dir / "deduction_rules.json"
        report_path = model_dir / "evaluation_report.json"
        old_rules: dict[str, Any] = {}
        if rules_path.exists():
            try:
                old_rules = json.loads(rules_path.read_text(encoding="utf-8"))
            except Exception:
                old_rules = {}
        recal = _recalibrate_thresholds_only(db, config.strict_mode)
        updated_rules = {
            **old_rules,
            "model": str(old_rules.get("model") or "logistic"),
            "warning_threshold": float(recal["thresholds"]["warning_threshold"]),
            "manual_review_threshold": float(recal["thresholds"]["manual_review_threshold"]),
            "critical_threshold": float(recal["thresholds"]["critical_threshold"]),
        }
        rules_path.write_text(json.dumps(updated_rules, indent=2), encoding="utf-8")
        report = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "mode": "threshold_recalibration_only",
            "reason": "insufficient_class_diversity",
            "rows_total": int(len(X)),
            "rows_train": 0,
            "rows_test": 0,
            "class_distribution": {"0": negatives, "1": positives},
            "feedback_only_samples": int(feedback_only_count),
            "pseudo_labeled_samples": int(max(0, len(X) - feedback_only_count)),
            "curated_hard_negative_samples": int(curated_hard_negative_count),
            "thresholds": recal["thresholds"],
            "distribution": recal["distribution"],
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {
            "bundle_path": str((model_dir / "supervised_bundle.joblib")),
            "rules_path": str(rules_path),
            "report_path": str(report_path),
            "sample_count": int(len(X)),
            "validation_count": 0,
            "precision": None,
            "recall": None,
            "f1_score": None,
            "roc_auc": None,
            "warning_threshold": float(recal["thresholds"]["warning_threshold"]),
            "manual_review_threshold": float(recal["thresholds"]["manual_review_threshold"]),
            "critical_threshold": float(recal["thresholds"]["critical_threshold"]),
            "summary": report,
        }

    train_idx, val_idx = _stratified_split(y, config.validation_split, config.seed)
    X_train = X[train_idx]
    y_train = y[train_idx]
    sw_train = sw[train_idx]
    X_val = X[val_idx]
    y_val = y[val_idx]

    mean = np.mean(X_train, axis=0)
    std = np.std(X_train, axis=0)
    std = np.where(std <= 1e-7, 1.0, std)
    X_train_n = (X_train - mean) / std
    X_val_n = (X_val - mean) / std

    class_weights = _class_balance_weights(y_train, config.class_balance_strength)
    sw_train_stage1 = sw_train * class_weights
    w_stage1, b_stage1 = _train_logistic_model(X_train_n, y_train, sw_train_stage1)
    sw_train_stage2, hard_negatives, hard_positives = _apply_hard_example_boost(
        X_train_n,
        y_train,
        sw_train_stage1,
        w_stage1,
        b_stage1,
        config.hard_negative_weight,
        config.hard_positive_weight,
        config.hard_example_min_prob,
    )
    w, b = _train_logistic_model(X_train_n, y_train, sw_train_stage2)
    val_prob = _sigmoid((X_val_n @ w) + b)
    threshold_metrics = _choose_threshold(y_val, val_prob, config.target_recall, config.max_false_positive_rate)

    manual_review_threshold = float(threshold_metrics["threshold"])
    if config.strict_mode:
        warning_threshold = float(max(0.20, manual_review_threshold - 0.14))
        critical_threshold = float(min(0.97, max(0.72, manual_review_threshold + 0.14)))
    else:
        warning_threshold = float(max(0.20, manual_review_threshold - 0.08))
        critical_threshold = float(min(0.97, max(0.70, manual_review_threshold + 0.18)))
    if critical_threshold <= manual_review_threshold:
        critical_threshold = min(0.97, manual_review_threshold + 0.10)

    warning_metrics = _metrics_at_threshold(y_val, val_prob, warning_threshold)
    critical_metrics = _metrics_at_threshold(y_val, val_prob, critical_threshold)
    auc = _roc_auc(y_val, val_prob)

    model_dir = Path("data/proctoring/models/supervised")
    model_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = model_dir / "supervised_bundle.joblib"
    rules_path = model_dir / "deduction_rules.json"
    report_path = model_dir / "evaluation_report.json"

    bundle = {
        "version": "event_risk_v1",
        "feature_space": "event_risk_v1",
        "feature_names": _feature_names(),
        "pre": {
            "type": "standard_scale_v1",
            "mean": mean.tolist(),
            "std": std.tolist(),
        },
        "models": {
            "logistic": {
                "type": "linear_logistic_v1",
                "weights": w.tolist(),
                "bias": float(b),
            },
        },
        "meta": {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "samples": int(len(X)),
            "validation_samples": int(len(X_val)),
            "feedback_only_samples": int(feedback_only_count),
            "pseudo_labeled_samples": int(max(0, len(X) - feedback_only_count - curated_hard_negative_count)),
            "curated_hard_negative_samples": int(curated_hard_negative_count),
            "positives": positives,
            "negatives": negatives,
            "target_recall": float(config.target_recall),
            "max_false_positive_rate": float(config.max_false_positive_rate),
            "class_balance_strength": float(config.class_balance_strength),
            "hard_negative_weight": float(config.hard_negative_weight),
            "hard_positive_weight": float(config.hard_positive_weight),
            "hard_example_min_prob": float(config.hard_example_min_prob),
            "curated_hard_negative_weight": float(config.curated_hard_negative_weight),
            "max_curated_hard_negatives": int(config.max_curated_hard_negatives),
            "hard_examples": {
                "hard_negatives": int(hard_negatives),
                "hard_positives": int(hard_positives),
            },
        },
    }
    joblib.dump(bundle, bundle_path)

    old_rules: dict[str, Any] = {}
    if rules_path.exists():
        try:
            old_rules = json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception:
            old_rules = {}
    updated_rules = {
        **old_rules,
        "model": "logistic",
        "warning_threshold": warning_threshold,
        "manual_review_threshold": manual_review_threshold,
        "critical_threshold": critical_threshold,
        "guardrails": {
            **(old_rules.get("guardrails") or {}),
            "require_two_signals": True,
            "require_min_confidence": 0.70,
            "always_manual_review_if_critical": True,
            "min_holdout_for_auto_deduction": 120,
        },
    }
    rules_path.write_text(json.dumps(updated_rules, indent=2), encoding="utf-8")

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "rows_total": int(len(X)),
        "rows_train": int(len(X_train)),
        "rows_test": int(len(X_val)),
        "class_distribution": {"0": negatives, "1": positives},
        "feedback_only_samples": int(feedback_only_count),
        "pseudo_labeled_samples": int(max(0, len(X) - feedback_only_count - curated_hard_negative_count)),
        "curated_hard_negative_samples": int(curated_hard_negative_count),
        "chosen_model": "logistic",
        "feature_space": "event_risk_v1",
        "metrics": {
            "validation_auc": float(auc),
            "warning_threshold": warning_metrics,
            "manual_review_threshold": threshold_metrics,
            "critical_threshold": critical_metrics,
        },
        "training_strategy": {
            "class_balance_strength": float(config.class_balance_strength),
            "hard_negative_weight": float(config.hard_negative_weight),
            "hard_positive_weight": float(config.hard_positive_weight),
            "hard_example_min_prob": float(config.hard_example_min_prob),
            "curated_hard_negative_weight": float(config.curated_hard_negative_weight),
            "max_curated_hard_negatives": int(config.max_curated_hard_negatives),
            "hard_examples": {
                "hard_negatives": int(hard_negatives),
                "hard_positives": int(hard_positives),
            },
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return {
        "bundle_path": str(bundle_path),
        "rules_path": str(rules_path),
        "report_path": str(report_path),
        "sample_count": int(len(X)),
        "validation_count": int(len(X_val)),
        "precision": float(threshold_metrics["precision"]),
        "recall": float(threshold_metrics["recall"]),
        "f1_score": float(threshold_metrics["f1"]),
        "roc_auc": float(auc),
        "warning_threshold": float(warning_threshold),
        "manual_review_threshold": float(manual_review_threshold),
        "critical_threshold": float(critical_threshold),
        "summary": report,
    }
